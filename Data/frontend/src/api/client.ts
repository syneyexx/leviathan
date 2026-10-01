import type {
  AgentCreatePayload,
  AgentDefinition,
  AgentEvent,
  AgentFleetSummary,
  AgentMission,
  AgentMissionLaunchPayload,
  AgentRosterEntry,
  AgentSignal,
  AgentSignalDeadLetter,
  AgentSignalDelivery,
  AgentSignalMetrics,
  AgentSignalStats,
  AgentCommunicationGraph,
  AgentsDashboard,
  FleetBulkResult,
  SignalCausalChain,
  WorkerPoolDefinition,
  WorkerPoolScaleResponse,
  WorkersListResponse,
  WorkerFabricDashboard,
  WorkerFabricPool,
  WorkerFabricWorker,
  AnalyticsAgentsResponse,
  AnalyticsDashboard,
  AnalyticsDatasetsResponse,
  AnalyticsOverview,
  AnalyticsToolsResponse,
  AnalyticsTrainingResponse,
  ApiErrorBody,
  BackupManifest,
  SqliteDatabaseStatus,
  SqliteQueryResult,
  SqliteTableInfo,
  SqliteTableDetail,
  SqliteRowsPage,
  SqliteMutationResult,
  SqliteIntegrityResult,
  SqliteOwnershipAudit,
  SqliteRuntimeStatus,
  ChatResponse,
  CognitionHealth,
  CognitionRunStatus,
  Conversation,
  DatasetFile,
  DatasetIndex,
  DatasetJob,
  DatasetBrainStatus,
  DatasetLearningEnrichedJob,
  DatasetLearningState,
  DatasetLearningStatus,
  DatasetLearningFleetResponse,
  DatasetOverview,
  DatasetPreviewRow,
  DatasetRecord,
  DatasetRecoveryAssessment,
  DatasetSemanticProfileSummary,
  DatasetVersion,
  ListDatasetJobsParams,
  ListDatasetJobsResult,
  DownloadJob,
  GatewaySnapshot,
  HardwareSnapshot,
  HealthResponse,
  HostOverviewResponse,
  HostSourceIngestionResponse,
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
  ModelHardwareInventory,
  ModelsStatus,
  ModelLoadOptions,
  ProviderControlCapabilities,
  ModelEstimateResult,
  ModelOptimizationRun,
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
  ResearchWebReadiness,
  ResearchWebProbe,
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
  ToolsOverview,
  ToolsLibraryItem,
  ToolsCapabilityDetail,
  ToolsRecentCall,
  PluginRecordPublic,
  SystemTelemetryResponse,
  McpCallRecord,
  McpServerPublic,
  McpToolRecord,
  MarketSimStatusResponse,
  PaperPortfolio,
  PortfolioDashboard,
  MarketBarsResponse,
  MarketDataSource,
  MarketStrategy,
  MarketStrategyVersion,
  MarketSimRun,
  MarketSimLiveState,
  MarketSimCapabilities,
  MarketSimPaperDeployment,
  TradeOrchestra,
  TradeOrchestraSummary,
  TradingDecision,
  TradingNewsFeed,
  TradingNewsItem,
  TradingNewsSignal,
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
  KnowledgeLibraryItem,
  KnowledgeLibraryOverview,
  KnowledgeLibraryListResponse,
  KnowledgeIngestionRecentItem,
  KnowledgeEmbeddingStatus,
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

import {
  ApiError,
  detailMessage,
  request,
  requestBlob,
} from "./http";
import { marketSimLabApi } from "./domains/marketSimLab";
import { researchCommandApi } from "./domains/researchCommand";
import { parseChatDonePayload, streamEventText } from "./chatContract";

export { ApiError, detailMessage, request, requestBlob };

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
    source?: string;
    trust?: string;
    tag?: string;
    pinned?: boolean;
    limit?: number;
    cursor?: string;
    sort?: string;
    conversation_id?: string;
    project_id?: string;
    scope?: string;
    created_after?: string;
    created_before?: string;
  }): Promise<import("../types/api").MemoryListResponse> {
    const params = new URLSearchParams();
    if (opts?.status) params.set("status", opts.status);
    if (opts?.kind) params.set("kind", opts.kind);
    if (opts?.source) params.set("source", opts.source);
    if (opts?.trust) params.set("trust", opts.trust);
    if (opts?.tag) params.set("tag", opts.tag);
    if (opts?.pinned != null) params.set("pinned", String(opts.pinned));
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    if (opts?.cursor) params.set("cursor", opts.cursor);
    if (opts?.sort) params.set("sort", opts.sort);
    if (opts?.conversation_id) params.set("conversation_id", opts.conversation_id);
    if (opts?.project_id) params.set("project_id", opts.project_id);
    if (opts?.scope) params.set("scope", opts.scope);
    if (opts?.created_after) params.set("created_after", opts.created_after);
    if (opts?.created_before) params.set("created_before", opts.created_before);
    const q = params.toString();
    return request<import("../types/api").MemoryListResponse>(`/api/memory${q ? `?${q}` : ""}`);
  },

  memoryOverview(): Promise<{ overview: import("../types/api").MemoryOverview }> {
    return request<{ overview: import("../types/api").MemoryOverview }>("/api/memory/overview");
  },

  memoryAnalytics(range = "7d"): Promise<{ analytics: import("../types/api").MemoryAnalytics }> {
    return request<{ analytics: import("../types/api").MemoryAnalytics }>(
      `/api/memory/analytics?range=${encodeURIComponent(range)}`,
    );
  },

  memoryActivity(limit = 40): Promise<{ activity: import("../types/api").MemoryActivityEvent[] }> {
    return request<{ activity: import("../types/api").MemoryActivityEvent[] }>(
      `/api/memory/activity?limit=${limit}`,
    );
  },

  memoryProcessing(): Promise<{ processing: import("../types/api").MemoryProcessingSettings }> {
    return request<{ processing: import("../types/api").MemoryProcessingSettings }>(
      "/api/memory/processing",
    );
  },

  patchMemoryProcessing(
    payload: Partial<import("../types/api").MemoryProcessingSettings>,
  ): Promise<{ processing: import("../types/api").MemoryProcessingSettings }> {
    return request<{ processing: import("../types/api").MemoryProcessingSettings }>(
      "/api/memory/processing",
      { method: "PATCH", body: JSON.stringify(payload) },
    );
  },

  memorySemanticIndex(): Promise<{
    semantic_index: import("../types/api").MemorySemanticIndexStatus;
  }> {
    return request<{ semantic_index: import("../types/api").MemorySemanticIndexStatus }>(
      "/api/memory/semantic-index",
    );
  },

  optimizeMemorySemanticIndex(): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>("/api/memory/semantic-index/optimize", {
      method: "POST",
    });
  },

  createMemory(payload: MemoryCreatePayload): Promise<{ memory: MemoryRecord; auto_embed?: unknown }> {
    return request<{ memory: MemoryRecord; auto_embed?: unknown }>("/api/memory", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  searchMemory(opts: {
    q: string;
    limit?: number;
    mode?: string;
    conversation_id?: string;
    project_id?: string;
    workspace_id?: string;
    scope?: string;
    kind?: string;
    source?: string;
  }): Promise<import("../types/api").MemorySearchResponse> {
    const params = new URLSearchParams();
    params.set("q", opts.q);
    if (opts.limit != null) params.set("limit", String(opts.limit));
    if (opts.mode) params.set("mode", opts.mode);
    if (opts.conversation_id) params.set("conversation_id", opts.conversation_id);
    if (opts.project_id) params.set("project_id", opts.project_id);
    if (opts.workspace_id) params.set("workspace_id", opts.workspace_id);
    if (opts.scope) params.set("scope", opts.scope);
    if (opts.kind) params.set("kind", opts.kind);
    if (opts.source) params.set("source", opts.source);
    return request<import("../types/api").MemorySearchResponse>(
      `/api/memory/search?${params.toString()}`,
    );
  },

  getMemory(memoryId: string): Promise<{ memory: MemoryRecord }> {
    return request<{ memory: MemoryRecord }>(`/api/memory/${encodeURIComponent(memoryId)}`);
  },

  patchMemory(
    memoryId: string,
    payload: import("../types/api").MemoryPatchPayload,
  ): Promise<{ memory: MemoryRecord }> {
    return request<{ memory: MemoryRecord }>(`/api/memory/${encodeURIComponent(memoryId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  pinMemory(memoryId: string): Promise<{ memory: MemoryRecord }> {
    return request<{ memory: MemoryRecord }>(
      `/api/memory/${encodeURIComponent(memoryId)}/pin`,
      { method: "POST" },
    );
  },

  unpinMemory(memoryId: string): Promise<{ memory: MemoryRecord }> {
    return request<{ memory: MemoryRecord }>(
      `/api/memory/${encodeURIComponent(memoryId)}/unpin`,
      { method: "POST" },
    );
  },

  correctMemory(
    memoryId: string,
    payload: { content: string; kind?: string; trust?: string; tags?: string[] },
  ): Promise<{ memory: MemoryRecord }> {
    return request<{ memory: MemoryRecord }>(
      `/api/memory/${encodeURIComponent(memoryId)}/correct`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },

  archiveMemory(memoryId: string): Promise<{ memory: MemoryRecord }> {
    return request<{ memory: MemoryRecord }>(
      `/api/memory/${encodeURIComponent(memoryId)}/archive`,
      { method: "POST" },
    );
  },

  restoreMemory(memoryId: string): Promise<{ memory: MemoryRecord }> {
    return request<{ memory: MemoryRecord }>(
      `/api/memory/${encodeURIComponent(memoryId)}/restore`,
      { method: "POST" },
    );
  },

  revokeMemory(memoryId: string): Promise<{ memory: MemoryRecord }> {
    return request<{ memory: MemoryRecord }>(
      `/api/memory/${encodeURIComponent(memoryId)}/revoke`,
      { method: "POST" },
    );
  },

  memoryFromConversation(payload: {
    conversation_id: string;
    content: string;
    kind?: string;
    trust?: string;
    tags?: string[];
    message_ids?: string[];
    from_assistant?: boolean;
  }): Promise<{ memory: MemoryRecord }> {
    return request<{ memory: MemoryRecord }>("/api/memory/from-conversation", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  metrics(): Promise<{ metrics: MetricsSnapshot }> {
    return request<{ metrics: MetricsSnapshot }>("/api/metrics");
  },

  listConversations(opts?: {
    q?: string;
    limit?: number;
    cursor?: string;
    signal?: AbortSignal;
  }): Promise<{
    conversations: Conversation[];
    items?: Conversation[];
    next_cursor?: string | null;
    has_more?: boolean;
    total?: number | null;
  }> {
    const params = new URLSearchParams();
    if (opts?.q) params.set("q", opts.q);
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    if (opts?.cursor) params.set("cursor", opts.cursor);
    const q = params.toString();
    return request<{
      conversations: Conversation[];
      items?: Conversation[];
      next_cursor?: string | null;
      has_more?: boolean;
      total?: number | null;
    }>(`/api/conversations${q ? `?${q}` : ""}`, opts?.signal ? { signal: opts.signal } : undefined);
  },

  createConversation(title = "New conversation"): Promise<{ conversation: Conversation }> {
    return request<{ conversation: Conversation }>("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ title }),
    });
  },

  getConversation(
    conversationId: string,
    opts?: {
      limit?: number;
      beforeId?: number;
      afterId?: number;
      includeTurns?: boolean;
      signal?: AbortSignal;
    },
  ): Promise<{
    conversation: Conversation;
    messages: Message[];
    has_more?: boolean;
    next_before_id?: number | null;
    next_after_id?: number | null;
    message_count?: number;
    turns?: Record<string, import("../types/api").ChatTurn>;
  }> {
    const params = new URLSearchParams();
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    if (opts?.beforeId != null) params.set("before_id", String(opts.beforeId));
    if (opts?.afterId != null) params.set("after_id", String(opts.afterId));
    if (opts?.includeTurns === false) params.set("include_turns", "false");
    const q = params.toString();
    return request(
      `/api/conversations/${encodeURIComponent(conversationId)}${q ? `?${q}` : ""}`,
      opts?.signal ? { signal: opts.signal } : undefined,
    );
  },

  cancelChat(payload: {
    turn_id?: string | null;
    chat_run_id?: string | null;
    run_id?: string | null;
    reason?: string;
  }): Promise<{
    turn_id?: string | null;
    chat_run_id?: string | null;
    run_state: string;
    cancelled: boolean;
    already_terminal: boolean;
    reason: string;
  }> {
    return request("/api/chat/cancel", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getChatTurn(turnId: string): Promise<{ turn: import("../types/api").ChatTurn }> {
    return request(`/api/chat/turns/${encodeURIComponent(turnId)}`);
  },

  getChatRunStatus(runId: string): Promise<{
    chat_run_id: string;
    run: { run_id: string; state: string; conversation_id?: string; error?: string } | null;
    turn: import("../types/api").ChatTurn | null;
    truth?: Record<string, boolean>;
  }> {
    return request(`/api/chat/runs/${encodeURIComponent(runId)}`);
  },

  /**
   * Create an ArtifactStore record from raw bytes (base64 over JSON).
   * Used by Chat attachments — never invent local filesystem paths.
   */
  createArtifactFromBytes(opts: {
    filename: string;
    content_type?: string;
    bytes: number[] | Uint8Array;
    conversation_id?: string;
    run_id?: string | null;
    artifact_type?: string;
    producer?: string;
  }): Promise<{
    artifact: {
      artifact_id: string;
      id?: string;
      artifact_type?: string;
      size_bytes?: number;
      declared_mime_type?: string;
      conversation_id?: string;
      [key: string]: unknown;
    };
  }> {
    const bytes =
      opts.bytes instanceof Uint8Array ? opts.bytes : new Uint8Array(opts.bytes);
    let binary = "";
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
    }
    const content = btoa(binary);
    return request("/api/artifacts", {
      method: "POST",
      body: JSON.stringify({
        content,
        content_base64: true,
        filename: opts.filename,
        artifact_type: opts.artifact_type || "file",
        mime_type: opts.content_type || "application/octet-stream",
        producer: opts.producer || "chat_ui",
        ...(opts.run_id ? { run_id: opts.run_id } : {}),
        ...(opts.conversation_id ? { conversation_id: opts.conversation_id } : {}),
      }),
    });
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
        ...(options.reasoningMode ? { reasoning_mode: options.reasoningMode } : {}),
        ...(options.collaborationStrategy
          ? { collaboration_strategy: options.collaborationStrategy }
          : {}),
        ...(options.stream != null ? { stream: options.stream } : {}),
        ...(options.idempotencyKey ? { idempotency_key: options.idempotencyKey } : {}),
        ...(options.artifactIds?.length ? { artifact_ids: options.artifactIds } : {}),
        ...(options.toolPolicy ? { tool_policy: options.toolPolicy } : {}),
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
      onToken?: (text: string, model?: string, meta?: { sequence?: number; kind?: string }) => void;
      onSnapshot?: (text: string, model?: string, meta?: { sequence?: number; kind?: string }) => void;
      onDone?: (data: ChatResponse) => void;
      onError?: (detail: string) => void;
      onCancelled?: (data: Record<string, unknown>) => void;
      /** Operational capability/tool status — never private CoT. */
      onCapabilityEvent?: (event: string, data: Record<string, unknown>) => void;
      /** Structured operational activity — never private CoT. */
      onActivity?: (data: Record<string, unknown>) => void;
    },
    fetchInit?: { signal?: AbortSignal },
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
        ...(options.reasoningMode ? { reasoning_mode: options.reasoningMode } : {}),
        ...(options.collaborationStrategy
          ? { collaboration_strategy: options.collaborationStrategy }
          : {}),
        ...(options.idempotencyKey ? { idempotency_key: options.idempotencyKey } : {}),
        ...(options.artifactIds?.length ? { artifact_ids: options.artifactIds } : {}),
        ...(options.toolPolicy ? { tool_policy: options.toolPolicy } : {}),
      }),
      signal: fetchInit?.signal,
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

    // Feature flag OFF / TEAM JSON → normal JSON response (still runtime-validated).
    if (!contentType.includes("text/event-stream")) {
      const raw = (await response.json()) as unknown;
      const parsed = parseChatDonePayload(raw);
      if (!parsed.ok) {
        const reason = parsed.failure.reason;
        const provisional = parsed.failure.provisional_content;
        const failureResponse = {
          conversation_id: parsed.failure.conversation_id ?? "",
          user_message: {
            id: 0,
            conversation_id: parsed.failure.conversation_id ?? "",
            role: "user" as const,
            content: "",
            created_at: new Date(0).toISOString(),
          },
          assistant_message: {
            id: 0,
            conversation_id: parsed.failure.conversation_id ?? "",
            role: "assistant" as const,
            content: provisional ?? "",
            created_at: new Date().toISOString(),
          },
          model: "",
          reasoning: { intent: "", complexity: "", use_knowledge: false, steps: [] },
          knowledge_sources: [],
          truth: {
            model_output_is_not_evidence: true,
            streaming_degraded: true,
          },
          protocol_failure: reason,
          provisional: true,
        } as ChatResponse & { protocol_failure?: string; provisional?: boolean };
        handlers.onDone?.(failureResponse);
        return failureResponse;
      }
      handlers.onDone?.(parsed.response);
      return parsed.response;
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new ApiError(503, "Streaming response body missing");
    }
    const decoder = new TextDecoder();
    let buffer = "";
    let donePayload: ChatResponse | null = null;
    let protocolFailure: string | null = null;
    let eventName = "message";
    const seenSequences = new Set<string>();
    let finalized = false;
    let streamClosed = false;

    const flushBlock = (block: string) => {
      // Normalize CRLF → LF so Windows-framed SSE parses correctly.
      const normalized = block.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
      const lines = normalized.split("\n");
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
        // Malformed JSON SSE: ignore the block; do not crash the page.
        eventName = "message";
        return;
      }
      const seq = typeof parsed.sequence === "number" ? parsed.sequence : undefined;
      const dedupeKey = seq !== undefined ? `${eventName}:${seq}` : undefined;
      if (dedupeKey) {
        if (seenSequences.has(dedupeKey)) {
          eventName = "message";
          return;
        }
        seenSequences.add(dedupeKey);
      }
      // After terminal done: ignore late tokens / snapshots (idempotent stream close).
      if (streamClosed && (eventName === "token" || eventName === "delta" || eventName === "snapshot" || eventName === "replace" || eventName === "meta")) {
        eventName = "message";
        return;
      }
      const text = streamEventText(parsed);
      const model = typeof parsed.model === "string" ? parsed.model : undefined;
      const kind = typeof parsed.kind === "string" ? parsed.kind : eventName;
      if (eventName === "meta") {
        handlers.onMeta?.(parsed);
        if (parsed.activity && typeof parsed.activity === "object") {
          // Projection snapshot may accompany meta; still not private CoT.
          handlers.onActivity?.(parsed.activity as Record<string, unknown>);
        }
      } else if (eventName === "activity") {
        handlers.onActivity?.(parsed);
      } else if (eventName === "token" || eventName === "delta") {
        // Prefer delta events; ignore duplicate token mirrors with same sequence.
        if (text) handlers.onToken?.(text, model, { sequence: seq, kind });
      } else if (eventName === "snapshot" || eventName === "replace") {
        if (text) handlers.onSnapshot?.(text, model, { sequence: seq, kind: eventName });
      } else if (eventName === "done") {
        if (finalized) {
          eventName = "message";
          return;
        }
        finalized = true;
        streamClosed = true;
        const validated = parseChatDonePayload(parsed);
        if (!validated.ok) {
          protocolFailure = validated.failure.reason;
          const provisional = validated.failure.provisional_content;
          // Surface a protocol-failure ChatResponse so callers can keep provisional text
          // without treating it as a canonical persisted success.
          donePayload = {
            conversation_id: validated.failure.conversation_id ?? "",
            user_message: {
              id: 0,
              conversation_id: validated.failure.conversation_id ?? "",
              role: "user",
              content: "",
              created_at: new Date(0).toISOString(),
            },
            assistant_message: {
              id: 0,
              conversation_id: validated.failure.conversation_id ?? "",
              role: "assistant",
              content: provisional ?? "",
              created_at: new Date().toISOString(),
            },
            model: "",
            reasoning: { intent: "", complexity: "", use_knowledge: false, steps: [] },
            knowledge_sources: [],
            truth: {
              model_output_is_not_evidence: true,
              streaming_degraded: true,
            },
            streamed: true,
            protocol_failure: protocolFailure,
            provisional: true,
          } as ChatResponse & { protocol_failure?: string; provisional?: boolean };
          handlers.onDone?.(donePayload);
        } else {
          donePayload = validated.response;
          handlers.onDone?.(donePayload);
        }
      } else if (eventName === "cancelled") {
        handlers.onCancelled?.(parsed);
        throw new ApiError(499, typeof parsed.reason === "string" ? parsed.reason : "cancelled");
      } else if (eventName === "error") {
        const detail =
          typeof parsed.detail === "string" ? parsed.detail : "stream error";
        handlers.onError?.(detail);
        throw new ApiError(503, detail);
      } else if (
        eventName.startsWith("tool.") ||
        eventName.startsWith("module.") ||
        eventName.startsWith("job.") ||
        eventName.startsWith("knowledge.") ||
        eventName.startsWith("artifact.") ||
        eventName.startsWith("source.") ||
        eventName === "capability.discovered" ||
        eventName === "capability_invoked" ||
        eventName === "capability_searched"
      ) {
        // Operational status only — ignore unknown private event names.
        handlers.onCapabilityEvent?.(eventName, parsed);
      }
      eventName = "message";
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // Accept both LF and CRLF event separators.
      let sep = buffer.search(/\r?\n\r?\n/);
      while (sep >= 0) {
        const block = buffer.slice(0, sep);
        const match = buffer.slice(sep).match(/^\r?\n\r?\n/);
        const skip = match ? match[0].length : 2;
        buffer = buffer.slice(sep + skip);
        flushBlock(block);
        sep = buffer.search(/\r?\n\r?\n/);
      }
    }
    if (buffer.trim()) {
      flushBlock(buffer);
    }
    if (!donePayload) {
      throw new ApiError(503, "Stream ended without done event");
    }
    // Protocol failure on done is returned (not thrown) so callers can keep
    // provisional streamed text without treating it as persisted success.
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

  /** GET /api/media/status — cached media engine posture (never runs FFmpeg). */
  mediaStatus(): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>("/api/media/status");
  },

  /** POST /api/media/request — enqueue media capability via JobRuntime. */
  mediaRequest(payload: {
    action: string;
    path?: string | null;
    prompt?: string | null;
    instruction?: string | null;
    wait_seconds?: number | null;
  }): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>("/api/media/request", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getJob(jobId: string): Promise<{ job: JobRecord }> {
    return request<{ job: JobRecord }>(`/api/jobs/${encodeURIComponent(jobId)}`);
  },

  cancelJob(jobId: string, reason?: string): Promise<{ job: JobRecord }> {
    const qs = reason ? `?reason=${encodeURIComponent(reason)}` : "";
    return request<{ job: JobRecord }>(
      `/api/jobs/${encodeURIComponent(jobId)}/cancel${qs}`,
      { method: "POST" },
    );
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

  listSqliteDatabases(): Promise<{ databases: SqliteDatabaseStatus[] }> {
    return request<{ databases: SqliteDatabaseStatus[] }>("/api/sqlite/databases");
  },

  sqliteDatabaseStatus(domain: string): Promise<{ database: SqliteDatabaseStatus }> {
    return request<{ database: SqliteDatabaseStatus }>(
      `/api/sqlite/databases/${encodeURIComponent(domain)}`,
    );
  },

  sqliteDatabaseTables(domain: string): Promise<{ domain: string; tables: SqliteTableInfo[] }> {
    return request<{ domain: string; tables: SqliteTableInfo[] }>(
      `/api/sqlite/databases/${encodeURIComponent(domain)}/tables`,
    );
  },

  sqliteTableDetail(domain: string, table: string): Promise<{ table: SqliteTableDetail }> {
    return request<{ table: SqliteTableDetail }>(
      `/api/sqlite/databases/${encodeURIComponent(domain)}/tables/${encodeURIComponent(table)}`,
    );
  },

  sqliteQueryRows(
    domain: string,
    table: string,
    body: {
      offset?: number;
      limit?: number;
      columns?: string[];
      filters?: Array<Record<string, unknown>>;
      search?: string;
      orderBy?: string[];
    } = {},
  ): Promise<SqliteRowsPage> {
    return request<SqliteRowsPage>(
      `/api/sqlite/databases/${encodeURIComponent(domain)}/tables/${encodeURIComponent(table)}/rows/query`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    );
  },

  sqliteQuery(domain: string, sql: string, limit = 200): Promise<SqliteQueryResult> {
    return request<SqliteQueryResult>("/api/sqlite/query", {
      method: "POST",
      body: JSON.stringify({ domain, sql, limit }),
    });
  },

  sqliteMutate(domain: string, confirmDomain: string, sql: string): Promise<SqliteMutationResult> {
    return request<SqliteMutationResult>("/api/sqlite/mutate", {
      method: "POST",
      body: JSON.stringify({ domain, confirmDomain, sql }),
    });
  },

  sqliteInsertRow(
    domain: string,
    confirmDomain: string,
    table: string,
    values: Record<string, unknown>,
  ): Promise<SqliteMutationResult> {
    return request<SqliteMutationResult>("/api/sqlite/rows/insert", {
      method: "POST",
      body: JSON.stringify({ domain, confirmDomain, table, values }),
    });
  },

  sqliteUpdateRow(
    domain: string,
    confirmDomain: string,
    table: string,
    identity: Record<string, unknown>,
    values: Record<string, unknown>,
  ): Promise<SqliteMutationResult> {
    return request<SqliteMutationResult>("/api/sqlite/rows/update", {
      method: "POST",
      body: JSON.stringify({ domain, confirmDomain, table, identity, values }),
    });
  },

  sqliteDeleteRow(
    domain: string,
    confirmDomain: string,
    table: string,
    identity: Record<string, unknown>,
  ): Promise<SqliteMutationResult> {
    return request<SqliteMutationResult>("/api/sqlite/rows/delete", {
      method: "POST",
      body: JSON.stringify({ domain, confirmDomain, table, identity }),
    });
  },

  sqliteIntegrity(
    domain: string,
    kind: "quick_check" | "integrity_check" | "foreign_key_check" = "quick_check",
    maxErrors = 100,
  ): Promise<SqliteIntegrityResult> {
    return request<SqliteIntegrityResult>("/api/sqlite/integrity", {
      method: "POST",
      body: JSON.stringify({ domain, kind, maxErrors }),
    });
  },

  sqliteWalCheckpoint(
    domain: string,
    confirmDomain: string,
    mode: "PASSIVE" | "FULL" | "RESTART" | "TRUNCATE" = "PASSIVE",
  ): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>("/api/sqlite/wal-checkpoint", {
      method: "POST",
      body: JSON.stringify({ domain, confirmDomain, mode }),
    });
  },

  sqliteOwnershipAudit(): Promise<SqliteOwnershipAudit> {
    return request<SqliteOwnershipAudit>("/api/sqlite/ownership-audit");
  },

  sqliteRuntime(): Promise<SqliteRuntimeStatus> {
    return request<SqliteRuntimeStatus>("/api/sqlite/runtime");
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

  getModule(moduleId: string): Promise<{ module: NonNullable<ModuleSnapshot["modules"]>[number] }> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}`);
  },

  discoverModules(): Promise<{ discovered: unknown[]; snapshot: ModuleSnapshot }> {
    return request("/api/modules/discover", { method: "POST" });
  },

  installModule(
    moduleId: string,
    payload: {
      force?: boolean;
      ref?: string;
      activate?: boolean;
      approval_id?: string;
      plan_hash?: string;
      auto_resolve_dependencies?: boolean;
    } = {},
  ): Promise<Record<string, unknown>> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/install`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  moduleInstallPlan(
    moduleId: string,
    payload: { force?: boolean; ref?: string; auto_resolve_dependencies?: boolean } = {},
  ): Promise<Record<string, unknown>> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/install-plan`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  moduleInstallState(moduleId: string): Promise<Record<string, unknown>> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/install-state`);
  },

  startModule(moduleId: string): Promise<Record<string, unknown>> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/start`, { method: "POST" });
  },

  stopModule(moduleId: string): Promise<Record<string, unknown>> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/stop`, { method: "POST" });
  },

  restartModule(moduleId: string): Promise<Record<string, unknown>> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/restart`, { method: "POST" });
  },

  ensureReadyModule(moduleId: string): Promise<Record<string, unknown>> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/ensure-ready`, { method: "POST" });
  },

  moduleHealth(moduleId: string): Promise<{ health: Record<string, unknown> }> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/health`);
  },

  moduleLogs(moduleId: string, limit = 200): Promise<{ lines: string[]; count: number }> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/logs?limit=${Math.max(1, Math.min(500, limit))}`);
  },

  moduleCapabilities(moduleId: string): Promise<{ capabilities: unknown[]; count: number }> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/capabilities`);
  },

  moduleJobs(moduleId: string): Promise<{
    jobs: Array<Record<string, unknown> | string>;
    active_job_ids?: string[];
    count: number;
    truth?: Record<string, boolean>;
  }> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/jobs`);
  },

  moduleActivity(
    moduleId: string,
    limit = 20,
  ): Promise<{
    module_id: string;
    events: Array<Record<string, unknown>>;
    count: number;
    truth?: Record<string, boolean>;
  }> {
    return request(
      `/api/modules/${encodeURIComponent(moduleId)}/activity?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  checkAllModuleUpdates(limit = 50): Promise<{
    results: Array<Record<string, unknown>>;
    errors: Array<Record<string, unknown>>;
    checked: number;
    error_count: number;
    snapshot: ModuleSnapshot;
    truth?: Record<string, boolean>;
  }> {
    return request(`/api/modules/check-updates?limit=${encodeURIComponent(String(limit))}`, {
      method: "POST",
    });
  },

  moduleVersions(moduleId: string): Promise<{ versions: Array<Record<string, unknown>>; count: number }> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/versions`);
  },

  moduleCheckUpdate(moduleId: string): Promise<{ result: Record<string, unknown> }> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/check-update`);
  },

  installModuleVersion(
    moduleId: string,
    payload: { ref?: string; activate?: boolean } = {},
  ): Promise<Record<string, unknown>> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/install-version`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  activateModuleVersion(moduleId: string, versionId: string): Promise<Record<string, unknown>> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/activate-version`, {
      method: "POST",
      body: JSON.stringify({ version_id: versionId }),
    });
  },

  rollbackModuleVersion(moduleId: string, versionId?: string): Promise<Record<string, unknown>> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/rollback-version`, {
      method: "POST",
      body: JSON.stringify(versionId ? { version_id: versionId } : {}),
    });
  },

  sweepIdleModules(): Promise<{ stopped: Array<Record<string, unknown>>; count: number }> {
    return request("/api/modules/sweep-idle", { method: "POST" });
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

  listSkills(params: {
    query?: string;
    include_catalog?: boolean;
    enabled_only?: boolean;
    classification?: "all" | "core" | "agent" | "external" | "tools" | string;
    limit?: number;
    offset?: number;
  } = {}): Promise<{
    skills: Array<Record<string, unknown>>;
    count: number;
    offset: number;
    limit: number;
    totals: {
      installed: number;
      catalog: number;
      total?: number;
      available?: number | null;
      external_packs?: number | null;
      tools?: number | null;
      issues?: number | null;
      agent_skills?: number | null;
      updates_available?: number | null;
      classifications?: Record<string, number | null | undefined>;
      truth?: Record<string, boolean>;
    };
    truth?: Record<string, boolean>;
  }> {
    const q = new URLSearchParams();
    if (params.query) q.set("query", params.query);
    if (params.include_catalog) q.set("include_catalog", "true");
    if (params.enabled_only) q.set("enabled_only", "true");
    if (params.classification) q.set("classification", params.classification);
    if (params.limit != null) q.set("limit", String(params.limit));
    if (params.offset != null) q.set("offset", String(params.offset));
    const qs = q.toString();
    return request(`/api/skills${qs ? `?${qs}` : ""}`);
  },

  getSkill(
    skillId: string,
    includeInstructions = false,
  ): Promise<{ skill: Record<string, unknown> }> {
    const q = includeInstructions ? "?include_instructions=true" : "";
    return request(`/api/skills/${encodeURIComponent(skillId)}${q}`);
  },

  setSkillEnabled(
    skillId: string,
    enabled: boolean,
  ): Promise<{ skill: Record<string, unknown> }> {
    return request(`/api/skills/${encodeURIComponent(skillId)}/enable`, {
      method: "POST",
      body: JSON.stringify({ enabled }),
    });
  },

  testSkill(skillId: string): Promise<{
    result: {
      ok: boolean;
      skill_id?: string;
      checks?: Array<{ name: string; passed: boolean; detail: string }>;
      truth?: Record<string, boolean>;
    };
    skill: Record<string, unknown>;
  }> {
    return request(`/api/skills/${encodeURIComponent(skillId)}/test`, {
      method: "POST",
      body: JSON.stringify({}),
    });
  },

  executeSkill(
    skillId: string,
    payload: { capability_id?: string; arguments?: Record<string, unknown> } = {},
  ): Promise<{
    skill_id: string;
    capability_id: string;
    result: Record<string, unknown>;
    truth?: Record<string, boolean>;
  }> {
    return request(`/api/skills/${encodeURIComponent(skillId)}/execute`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listWorkflows(
    limit = 100,
    opts?: { status?: string; category?: string; q?: string; offset?: number },
  ): Promise<{ workflows: WorkflowRecord[] }> {
    const params = new URLSearchParams();
    params.set("limit", String(limit));
    if (opts?.offset != null) params.set("offset", String(opts.offset));
    if (opts?.status) params.set("status", opts.status);
    if (opts?.category) params.set("category", opts.category);
    if (opts?.q) params.set("q", opts.q);
    return request(`/api/workflows?${params.toString()}`);
  },

  workflowsOverview(opts?: {
    chartHours?: number;
    topDays?: number;
  }): Promise<{ overview: import("../types/api").WorkflowOverview }> {
    const params = new URLSearchParams();
    if (opts?.chartHours != null) params.set("chartHours", String(opts.chartHours));
    if (opts?.topDays != null) params.set("topDays", String(opts.topDays));
    const q = params.toString();
    return request(`/api/workflows/overview${q ? `?${q}` : ""}`);
  },

  workflowTemplates(limit = 50): Promise<{ templates: WorkflowRecord[] }> {
    return request(`/api/workflows/templates?limit=${encodeURIComponent(String(limit))}`);
  },

  workflowPalette(): Promise<{ palette: import("../types/api").WorkflowPalette }> {
    return request("/api/workflows/palette");
  },

  createWorkflow(payload: WorkflowCreatePayload): Promise<{ workflow: WorkflowRecord }> {
    return request("/api/workflows", { method: "POST", body: JSON.stringify(payload) });
  },

  getWorkflow(workflowId: string): Promise<{ workflow: WorkflowRecord }> {
    return request(`/api/workflows/${encodeURIComponent(workflowId)}`);
  },

  patchWorkflow(
    workflowId: string,
    payload: Record<string, unknown>,
  ): Promise<{ workflow: WorkflowRecord }> {
    return request(`/api/workflows/${encodeURIComponent(workflowId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  deleteWorkflow(workflowId: string, hard = false): Promise<{ ok: boolean }> {
    return request(
      `/api/workflows/${encodeURIComponent(workflowId)}?hard=${hard ? "true" : "false"}`,
      { method: "DELETE" },
    );
  },

  duplicateWorkflow(
    workflowId: string,
    name?: string,
  ): Promise<{ workflow: WorkflowRecord }> {
    return request(`/api/workflows/${encodeURIComponent(workflowId)}/duplicate`, {
      method: "POST",
      body: JSON.stringify(name ? { name } : {}),
    });
  },

  listWorkflowVersions(
    workflowId: string,
  ): Promise<{ versions: Array<Record<string, unknown>> }> {
    return request(`/api/workflows/${encodeURIComponent(workflowId)}/versions`);
  },

  restoreWorkflowVersion(
    workflowId: string,
    version: number,
  ): Promise<{ workflow: WorkflowRecord }> {
    return request(`/api/workflows/${encodeURIComponent(workflowId)}/restore-version`, {
      method: "POST",
      body: JSON.stringify({ version }),
    });
  },

  listWorkflowExecutions(
    workflowId: string,
    limit = 50,
  ): Promise<{ executions: import("../types/api").WorkflowExecution[] }> {
    return request(
      `/api/workflows/${encodeURIComponent(workflowId)}/executions?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  workflowLogs(
    workflowId: string,
    opts?: { executionId?: string; limit?: number },
  ): Promise<{ logs: Array<Record<string, unknown>> }> {
    const params = new URLSearchParams();
    if (opts?.executionId) params.set("executionId", opts.executionId);
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    const q = params.toString();
    return request(`/api/workflows/${encodeURIComponent(workflowId)}/logs${q ? `?${q}` : ""}`);
  },

  runWorkflow(
    workflowId: string,
    payload?: { inputs?: Record<string, unknown>; idempotency_key?: string },
  ): Promise<{
    workflow: WorkflowRecord;
    execution?: import("../types/api").WorkflowExecution;
    job?: Record<string, unknown> | null;
    mode?: string;
  }> {
    return request(`/api/workflows/${encodeURIComponent(workflowId)}/run`, {
      method: "POST",
      body: JSON.stringify(payload || {}),
    });
  },

  cancelWorkflow(workflowId: string): Promise<{ workflow: WorkflowRecord }> {
    return request(`/api/workflows/${encodeURIComponent(workflowId)}/cancel`, { method: "POST" });
  },

  getWorkflowExecution(
    executionId: string,
  ): Promise<{ execution: import("../types/api").WorkflowExecution }> {
    return request(`/api/workflow-executions/${encodeURIComponent(executionId)}`);
  },

  cancelWorkflowExecution(
    executionId: string,
  ): Promise<{ execution?: import("../types/api").WorkflowExecution; workflow: WorkflowRecord }> {
    return request(`/api/workflow-executions/${encodeURIComponent(executionId)}/cancel`, {
      method: "POST",
    });
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

  getKnowledgeHealth(): Promise<{ health: Record<string, unknown> }> {
    return request("/api/knowledge/health");
  },

  getKnowledgeLibraryOverview(): Promise<{ overview: KnowledgeLibraryOverview }> {
    return request("/api/knowledge/library/overview");
  },

  listKnowledgeLibrary(opts: {
    q?: string;
    type?: string;
    tag?: string;
    status?: string;
    date_from?: string;
    date_to?: string;
    sort?: string;
    limit?: number;
    offset?: number;
    cursor?: string;
  } = {}): Promise<KnowledgeLibraryListResponse> {
    const params = new URLSearchParams();
    if (opts.q) params.set("q", opts.q);
    if (opts.type) params.set("type", opts.type);
    if (opts.tag) params.set("tag", opts.tag);
    if (opts.status) params.set("status", opts.status);
    if (opts.date_from) params.set("date_from", opts.date_from);
    if (opts.date_to) params.set("date_to", opts.date_to);
    if (opts.sort) params.set("sort", opts.sort);
    if (opts.limit != null) params.set("limit", String(opts.limit));
    if (opts.offset != null) params.set("offset", String(opts.offset));
    if (opts.cursor) params.set("cursor", opts.cursor);
    const q = params.toString();
    return request(`/api/knowledge/library${q ? `?${q}` : ""}`);
  },

  getKnowledgeLibraryDocument(documentId: string): Promise<{ document: KnowledgeLibraryItem }> {
    return request(`/api/knowledge/library/${encodeURIComponent(documentId)}`);
  },

  setKnowledgeLibraryTags(
    documentId: string,
    tags: string[],
    mode: "replace" | "add" = "replace",
  ): Promise<{ document_id: string; tags: string[]; mode: string }> {
    return request(`/api/knowledge/library/${encodeURIComponent(documentId)}/tags`, {
      method: "POST",
      body: JSON.stringify({ tags, mode }),
    });
  },

  getKnowledgeLibraryPreview(documentId: string): Promise<{
    preview: Record<string, unknown>;
    document: KnowledgeLibraryItem | null;
  }> {
    return request(`/api/knowledge/library/${encodeURIComponent(documentId)}/preview`);
  },

  getKnowledgeLibraryContentChunks(
    documentId: string,
    opts: { offset?: number; limit?: number } = {},
  ): Promise<{
    document_id: string;
    chunks: KnowledgeChunk[];
    total: number;
    offset: number;
    limit: number;
    has_more: boolean;
    next_offset: number | null;
  }> {
    const params = new URLSearchParams();
    if (opts.offset != null) params.set("offset", String(opts.offset));
    if (opts.limit != null) params.set("limit", String(opts.limit));
    const q = params.toString();
    return request(
      `/api/knowledge/library/${encodeURIComponent(documentId)}/content-chunks${q ? `?${q}` : ""}`,
    );
  },

  getKnowledgeLibraryEmbeddings(
    documentId: string,
  ): Promise<{ embeddings: KnowledgeEmbeddingStatus }> {
    return request(`/api/knowledge/library/${encodeURIComponent(documentId)}/embeddings`);
  },

  getKnowledgeLibraryRelations(
    documentId: string,
    limit = 50,
  ): Promise<{ document_id: string; relations: Array<Record<string, unknown>>; total: number }> {
    return request(
      `/api/knowledge/library/${encodeURIComponent(documentId)}/relations?limit=${Math.max(1, Math.min(200, limit))}`,
    );
  },

  getKnowledgeLibraryRelated(
    documentId: string,
    limit = 12,
  ): Promise<{ document_id: string; related: KnowledgeLibraryItem[]; total: number }> {
    return request(
      `/api/knowledge/library/${encodeURIComponent(documentId)}/related?limit=${Math.max(1, Math.min(40, limit))}`,
    );
  },

  knowledgeLibraryDownloadUrl(documentId: string): string {
    return `/api/knowledge/library/${encodeURIComponent(documentId)}/download`;
  },

  knowledgeLibraryContentUrl(documentId: string): string {
    return `/api/knowledge/library/${encodeURIComponent(documentId)}/content`;
  },

  getKnowledgeLibraryIngestionCapabilities(): Promise<Record<string, unknown>> {
    return request("/api/knowledge/library/ingestion/capabilities");
  },

  async uploadKnowledgeLibraryFile(file: File): Promise<Record<string, unknown>> {
    const form = new FormData();
    form.append("file", file, file.name);
    return request("/api/knowledge/library/ingestion/upload", {
      method: "POST",
      body: form,
    });
  },

  listKnowledgeLibraryRecentIngestions(
    limit = 20,
    offset = 0,
  ): Promise<{ items: KnowledgeIngestionRecentItem[]; limit: number; offset: number }> {
    return request(
      `/api/knowledge/library/ingestion/recent?limit=${Math.max(1, Math.min(100, limit))}&offset=${Math.max(0, offset)}`,
    );
  },

  getKnowledgeLibraryIngestionStatus(
    sourceId: string,
  ): Promise<{ source_id: string; progress: Record<string, unknown> }> {
    return request(`/api/knowledge/library/ingestion/${encodeURIComponent(sourceId)}`);
  },

  cancelKnowledgeLibraryIngestion(
    sourceId: string,
  ): Promise<{ progress: Record<string, unknown> }> {
    return request(`/api/knowledge/library/ingestion/${encodeURIComponent(sourceId)}/cancel`, {
      method: "POST",
    });
  },

  retryKnowledgeLibraryIngestion(
    sourceId: string,
    failedOnly = true,
  ): Promise<Record<string, unknown>> {
    return request(
      `/api/knowledge/library/ingestion/${encodeURIComponent(sourceId)}/retry?failed_only=${failedOnly ? "true" : "false"}`,
      { method: "POST" },
    );
  },

  retryKnowledgeLibraryIngestionBrain(sourceId: string): Promise<Record<string, unknown>> {
    return request(`/api/knowledge/library/ingestion/${encodeURIComponent(sourceId)}/brain-retry`, {
      method: "POST",
    });
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

  /** GET /api/evaluation/reports — persisted evaluation evidence only. */
  listEvaluationReports(
    limit = 50,
  ): Promise<{ reports: unknown[]; truth?: Record<string, boolean> }> {
    const q = new URLSearchParams({ limit: String(limit) });
    return request<{ reports: unknown[]; truth?: Record<string, boolean> }>(
      `/api/evaluation/reports?${q.toString()}`,
    );
  },

  /**
   * POST /api/evaluation/{suite} — enqueue suite on evaluation worker.
   * Pass path segments such as "neuro", "foundation", or "release/validate".
   */
  runEvaluationSuite(
    path: string,
    body?: Record<string, unknown>,
  ): Promise<{ job?: unknown; queued?: boolean; suite_id?: string; report?: unknown }> {
    const suite = String(path || "")
      .replace(/^\/+/, "")
      .replace(/^api\/evaluation\//, "");
    if (!suite) {
      return Promise.reject(new Error("evaluation suite path is required"));
    }
    return request(`/api/evaluation/${suite}`, {
      method: "POST",
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
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

  modelsHardware(): Promise<{
    hardware: ModelHardwareInventory;
    reservations: Record<string, unknown>[];
    residency: ModelResidency[];
  }> {
    return request("/api/models/hardware");
  },

  modelsReservations(): Promise<{ reservations: Record<string, unknown>[] }> {
    return request("/api/models/reservations");
  },

  updateHardwarePolicy(payload: Record<string, unknown>): Promise<{
    policy: Record<string, unknown>;
    hardware: ModelHardwareInventory;
  }> {
    return request("/api/models/hardware/policy", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  placementPreflight(
    modelId: string,
    payload?: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    return request(`/api/models/${encodeURIComponent(modelId)}/placement-preflight`, {
      method: "POST",
      body: JSON.stringify(payload ?? {}),
    });
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

  /* ---------- Models V2 — capabilities, estimate, optimizer ---------- */

  getProviderCapabilities(providerId: string): Promise<ProviderControlCapabilities> {
    return request(`/api/models/providers/${encodeURIComponent(providerId)}/capabilities`);
  },

  estimateModelLoad(modelId: string, options: Partial<ModelLoadOptions> = {}): Promise<ModelEstimateResult> {
    return request(`/api/models/${encodeURIComponent(modelId)}/estimate`, {
      method: "POST",
      body: JSON.stringify(options),
    });
  },

  startModelOptimization(
    modelId: string,
    payload: Partial<ModelLoadOptions> & {
      objectives?: Record<string, boolean>;
      maxCandidates?: number;
      deadlineSeconds?: number;
    } = {},
  ): Promise<{ queued: boolean; optimization: ModelOptimizationRun }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/optimization`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getModelOptimization(runId: string): Promise<{ optimization: ModelOptimizationRun }> {
    return request(`/api/models/optimization/${encodeURIComponent(runId)}`);
  },

  listModelOptimizations(modelId: string): Promise<{ optimizations: ModelOptimizationRun[] }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/optimization`);
  },

  cancelModelOptimization(runId: string): Promise<{ optimization: ModelOptimizationRun }> {
    return request(`/api/models/optimization/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
    });
  },

  /* ---------- Datasets ---------- */

  listDatasets(
    limit = 100,
    params?: {
      offset?: number;
      q?: string;
      status?: string;
      source?: string;
      sourceType?: string;
      sourceScope?: "local" | "external";
      indexed?: boolean;
      type?: string;
      detectedFormat?: string;
      category?: string;
      tags?: string;
      split?: string;
      sort?: string;
      updatedAfter?: string;
      updatedBefore?: string;
      cursor?: string;
      includeBrain?: boolean;
      includeQuality?: boolean;
    },
  ): Promise<{
    datasets: DatasetRecord[];
    total?: number;
    limit?: number;
    offset?: number;
    sort?: string;
    hasMore?: boolean;
    nextOffset?: number | null;
    nextCursor?: string | null;
    truth?: Record<string, unknown>;
  }> {
    const sp = new URLSearchParams();
    sp.set("limit", String(limit));
    if (params?.offset != null) sp.set("offset", String(params.offset));
    if (params?.q) sp.set("q", params.q);
    if (params?.status) sp.set("status", params.status);
    if (params?.source) sp.set("source", params.source);
    if (params?.sourceType) sp.set("sourceType", params.sourceType);
    if (params?.sourceScope) sp.set("sourceScope", params.sourceScope);
    if (params?.indexed != null) sp.set("indexed", params.indexed ? "true" : "false");
    if (params?.type) sp.set("type", params.type);
    if (params?.detectedFormat) sp.set("detectedFormat", params.detectedFormat);
    if (params?.category) sp.set("category", params.category);
    if (params?.tags) sp.set("tags", params.tags);
    if (params?.split) sp.set("split", params.split);
    if (params?.sort) sp.set("sort", params.sort);
    if (params?.updatedAfter) sp.set("updatedAfter", params.updatedAfter);
    if (params?.updatedBefore) sp.set("updatedBefore", params.updatedBefore);
    if (params?.cursor) sp.set("cursor", params.cursor);
    if (params?.includeBrain === false) sp.set("includeBrain", "false");
    if (params?.includeQuality === false) sp.set("includeQuality", "false");
    return request(`/api/datasets?${sp.toString()}`);
  },

  bulkIndexDatasets(payload: {
    datasetIds: string[];
    rebuild?: boolean;
  }): Promise<import("../types/api").DatasetBulkResult> {
    return request("/api/datasets/bulk/index", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  bulkMaterializeDatasets(payload: {
    datasetIds: string[];
  }): Promise<import("../types/api").DatasetBulkResult> {
    return request("/api/datasets/bulk/materialize", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getDatasetsOverview(): Promise<{ overview: DatasetOverview }> {
    return request("/api/datasets/overview");
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
    learningState?: DatasetLearningState;
    brain?: DatasetLearningState | DatasetBrainStatus;
    brainStatus?: string;
    learned?: boolean;
    canonicalState?: string;
  }> {
    return request(`/api/datasets/${encodeURIComponent(datasetId)}`);
  },

  getDatasetLearningState(datasetId: string): Promise<{
    learningState: DatasetLearningState;
    truth?: Record<string, unknown>;
  }> {
    return request(`/api/datasets/${encodeURIComponent(datasetId)}/learning-state`);
  },

  getDatasetRecovery(datasetId: string): Promise<{ recovery: DatasetRecoveryAssessment }> {
    return request(`/api/datasets/${encodeURIComponent(datasetId)}/recovery`);
  },

  analyzeDatasetSemantic(
    datasetId: string,
    payload?: {
      versionId?: string | null;
      syncArtifacts?: boolean;
      enqueue?: boolean;
    },
  ): Promise<{
    datasetId?: string;
    versionId?: string;
    semanticProfile?: DatasetSemanticProfileSummary & Record<string, unknown>;
    dataset?: DatasetRecord;
    job?: DatasetJob;
    recovery?: Record<string, unknown>;
  }> {
    return request(`/api/datasets/${encodeURIComponent(datasetId)}/semantic/analyze`, {
      method: "POST",
      body: JSON.stringify(payload ?? {}),
    });
  },

  patchDatasetSemantic(
    datasetId: string,
    payload: {
      displayName?: string | null;
      primaryCategory?: string | null;
      secondaryCategory?: string | null;
      tags?: string[] | null;
      summary?: string | null;
      versionId?: string | null;
      syncArtifacts?: boolean;
    },
  ): Promise<{
    datasetId: string;
    versionId?: string | null;
    semanticProfile: DatasetSemanticProfileSummary & Record<string, unknown>;
    dataset: DatasetRecord;
    recovery?: Record<string, unknown>;
    truth?: Record<string, unknown>;
  }> {
    return request(`/api/datasets/${encodeURIComponent(datasetId)}/semantic`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  getDatasetCatalogStatus(): Promise<Record<string, unknown>> {
    return request("/api/datasets/catalog");
  },

  reconcileDatasetCatalog(rebuild = false): Promise<Record<string, unknown>> {
    return request(`/api/datasets/catalog/reconcile?rebuild=${encodeURIComponent(String(rebuild))}`, {
      method: "POST",
    });
  },

  reconcileDatasetLearning(): Promise<{
    interrupted: DatasetJob[];
    staleReconciled: DatasetJob[];
    truth?: Record<string, boolean>;
  }> {
    return request("/api/datasets/learning/reconcile", { method: "POST" });
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

  contaminationScanDatasetVersion(
    datasetId: string,
    versionId: string,
    payload: { sealedCases?: unknown[]; threshold?: number } = {},
  ): Promise<{ job: DatasetJob }> {
    return request(
      `/api/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/contamination-scan`,
      {
        method: "POST",
        body: JSON.stringify({
          sealedCases: payload.sealedCases ?? [],
          threshold: payload.threshold ?? 0.35,
        }),
      },
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

  listDatasetJobs(
    datasetIdOrOptions?: string | ListDatasetJobsParams,
    limit = 100,
  ): Promise<ListDatasetJobsResult> {
    const opts: ListDatasetJobsParams =
      typeof datasetIdOrOptions === "string" || datasetIdOrOptions == null
        ? { datasetId: datasetIdOrOptions, limit }
        : { limit, ...datasetIdOrOptions };
    const params = new URLSearchParams();
    params.set("limit", String(opts.limit ?? 100));
    if (opts.offset != null) params.set("offset", String(opts.offset));
    if (opts.datasetId) params.set("datasetId", opts.datasetId);
    if (opts.status) params.set("status", opts.status);
    if (opts.jobType) params.set("jobType", opts.jobType);
    if (opts.createdAfter) params.set("createdAfter", opts.createdAfter);
    if (opts.createdBefore) params.set("createdBefore", opts.createdBefore);
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
    active: DatasetLearningEnrichedJob[];
    recent: DatasetLearningEnrichedJob[];
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

  listLearningFleet(limit = 200): Promise<DatasetLearningFleetResponse> {
    return request(`/api/datasets/learning/fleet?limit=${encodeURIComponent(String(limit))}`);
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

  getResearchWebReadiness(): Promise<{ readiness: ResearchWebReadiness }> {
    return request("/api/research/web/readiness");
  },

  probeResearchWeb(payload?: {
    query?: string;
    limit?: number;
  }): Promise<{
    probe: ResearchWebProbe;
    queued?: boolean;
    job?: JobRecord;
    job_id?: string;
    truth?: Record<string, unknown>;
  }> {
    return request("/api/research/web/probe", {
      method: "POST",
      body: JSON.stringify(payload ?? {}),
    });
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
  ): Promise<{
    project: ResearchProject;
    plan: ResearchPlan | null;
    queued?: boolean;
    job?: JobRecord;
    job_id?: string;
    status?: string;
    truth?: Record<string, unknown>;
  }> {
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

  hostOverview(): Promise<HostOverviewResponse> {
    return request<HostOverviewResponse>("/api/host/overview");
  },

  hostSourceIngestion(limit = 50): Promise<HostSourceIngestionResponse> {
    return request<HostSourceIngestionResponse>(
      `/api/host/source-ingestion?limit=${encodeURIComponent(String(limit))}`,
    );
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

  capabilitiesOverview(periodDays = 7): Promise<{ overview: ToolsOverview }> {
    return request(`/api/capabilities/overview?period_days=${encodeURIComponent(String(periodDays))}`);
  },

  capabilitiesLibrary(opts?: {
    q?: string;
    category?: string;
    source?: string;
    sort?: string;
    limit?: number;
    offset?: number;
  }): Promise<{
    tools: ToolsLibraryItem[];
    total: number;
    limit: number;
    offset: number;
    has_more: boolean;
  }> {
    const params = new URLSearchParams();
    if (opts?.q) params.set("q", opts.q);
    if (opts?.category) params.set("category", opts.category);
    if (opts?.source) params.set("source", opts.source);
    if (opts?.sort) params.set("sort", opts.sort);
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    if (opts?.offset != null) params.set("offset", String(opts.offset));
    const q = params.toString();
    return request(`/api/capabilities/library${q ? `?${q}` : ""}`);
  },

  capabilityDetail(
    capabilityId: string,
    opts?: { receiptLimit?: number },
  ): Promise<ToolsCapabilityDetail> {
    const params = new URLSearchParams({ detail: "true" });
    if (opts?.receiptLimit != null) params.set("receipt_limit", String(opts.receiptLimit));
    return request(`/api/capabilities/${encodeURIComponent(capabilityId)}?${params}`);
  },

  capabilityReceipts(
    capabilityId: string,
    limit = 50,
  ): Promise<{ capability_id: string; receipts: ToolsRecentCall[]; usage?: ToolsCapabilityDetail["usage"] }> {
    return request(
      `/api/capabilities/receipts/by-capability/${encodeURIComponent(capabilityId)}?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  createCustomCapability(payload: {
    name: string;
    description?: string;
    wraps_capability_id: string;
    capability_id?: string;
    version?: string;
    metadata?: Record<string, unknown>;
  }): Promise<{ custom: Record<string, unknown>; capability: CapabilityListItem | null }> {
    return request("/api/capabilities/custom", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  updateCustomCapability(
    capabilityId: string,
    payload: {
      name?: string;
      description?: string;
      enabled?: boolean;
      version?: string;
      metadata?: Record<string, unknown>;
      expected_revision?: number;
    },
  ): Promise<{ custom: Record<string, unknown>; capability: CapabilityListItem | null }> {
    return request(`/api/capabilities/custom/${encodeURIComponent(capabilityId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  deleteCustomCapability(capabilityId: string): Promise<{ ok: boolean }> {
    return request(`/api/capabilities/custom/${encodeURIComponent(capabilityId)}`, {
      method: "DELETE",
    });
  },

  listPlugins(): Promise<{ plugins: PluginRecordPublic[] }> {
    return request("/api/plugins");
  },

  enablePlugin(pluginId: string): Promise<{ plugin: PluginRecordPublic }> {
    return request(`/api/plugins/${encodeURIComponent(pluginId)}/enable`, { method: "POST" });
  },

  disablePlugin(pluginId: string): Promise<{ plugin: PluginRecordPublic }> {
    return request(`/api/plugins/${encodeURIComponent(pluginId)}/disable`, { method: "POST" });
  },

  executeCapability(
    capabilityId: string,
    arguments_: Record<string, unknown> = {},
    opts?: {
      requested_by?: string;
      approval_id?: string;
      idempotency_key?: string;
      run_id?: string;
      job_id?: string;
      trace_id?: string;
    },
  ): Promise<{ result: unknown }> {
    return request(`/api/capabilities/${encodeURIComponent(capabilityId)}/execute`, {
      method: "POST",
      body: JSON.stringify({
        arguments: arguments_,
        requested_by: opts?.requested_by ?? "ui",
        approval_id: opts?.approval_id,
        idempotency_key: opts?.idempotency_key,
        run_id: opts?.run_id,
        job_id: opts?.job_id,
        trace_id: opts?.trace_id,
      }),
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

  versionMarketStrategy(
    strategyId: string,
    payload: {
      name?: string;
      description?: string;
      tags?: string[];
      parameters?: Record<string, unknown>;
      entryRules?: Record<string, unknown>;
      exitRules?: Record<string, unknown>;
      riskRules?: Record<string, unknown>;
      requiredTimeframes?: string[];
      brainDependencies?: string[];
      changelog?: string;
    },
  ): Promise<{ strategy: MarketStrategy; version: MarketStrategyVersion }> {
    return request(`/api/market-sim/strategies/${encodeURIComponent(strategyId)}/versions`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  forkMarketStrategy(
    strategyId: string,
    payload?: { name?: string },
  ): Promise<{ strategy: MarketStrategy; version: MarketStrategyVersion }> {
    return request(`/api/market-sim/strategies/${encodeURIComponent(strategyId)}/fork`, {
      method: "POST",
      body: JSON.stringify(payload ?? {}),
    });
  },

  archiveMarketStrategy(strategyId: string): Promise<{ strategy: MarketStrategy }> {
    return request(`/api/market-sim/strategies/${encodeURIComponent(strategyId)}/archive`, {
      method: "POST",
    });
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
    decisionCadence?: string;
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

  marketSimCapabilities(): Promise<MarketSimCapabilities> {
    return request("/api/market-sim/capabilities");
  },

  listPaperDeployments(params?: {
    strategyId?: string;
    mode?: string;
    limit?: number;
  }): Promise<{ deployments: MarketSimPaperDeployment[]; truth: Record<string, unknown> }> {
    const q = new URLSearchParams();
    if (params?.strategyId) q.set("strategyId", params.strategyId);
    if (params?.mode) q.set("mode", params.mode);
    if (params?.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request(`/api/market-sim/paper/deployments${qs ? `?${qs}` : ""}`);
  },

  createPaperDeployment(payload: {
    strategyId: string;
    strategyVersion?: number | null;
    universe?: string[];
    feedId?: string;
    mode?: "shadow" | "autonomous_paper" | string;
    symbol?: string;
    brokerId?: string;
    providerId?: string;
    initialCash?: number;
    riskConfig?: Record<string, unknown>;
    sizingConfig?: Record<string, unknown>;
    qualificationRefs?: Record<string, unknown>;
  }): Promise<Record<string, unknown>> {
    return request("/api/market-sim/paper/deployments", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getPaperDeployment(deploymentId: string): Promise<{ deployment: MarketSimPaperDeployment }> {
    return request(`/api/market-sim/paper/deployments/${encodeURIComponent(deploymentId)}`);
  },

  shadowObserveDeployment(
    deploymentId: string,
    payload?: { signalSide?: string; proposedQty?: number | null; riskDecision?: string },
  ): Promise<Record<string, unknown>> {
    return request(
      `/api/market-sim/paper/deployments/${encodeURIComponent(deploymentId)}/shadow-observe`,
      { method: "POST", body: JSON.stringify(payload || {}) },
    );
  },

  promotePaperDeployment(
    deploymentId: string,
    payload: {
      targetLevel: string;
      sealedAttemptId?: string | null;
      minShadowObservations?: number;
      minPaperSteps?: number;
      acceptanceCriteria?: Record<string, unknown>;
    },
  ): Promise<Record<string, unknown>> {
    return request(
      `/api/market-sim/paper/deployments/${encodeURIComponent(deploymentId)}/promote`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },

  autonomousPaperStep(
    deploymentId: string,
    payload?: { side?: string; qty?: number | null },
  ): Promise<Record<string, unknown>> {
    return request(
      `/api/market-sim/paper/deployments/${encodeURIComponent(deploymentId)}/autonomous-step`,
      { method: "POST", body: JSON.stringify(payload || {}) },
    );
  },

  reviewPaperDeploymentDrift(
    deploymentId: string,
    payload: {
      baselineMetrics: Record<string, number>;
      observedMetrics: Record<string, number>;
      relativeThreshold?: number;
      spawnChallenger?: boolean;
    },
  ): Promise<Record<string, unknown>> {
    return request(
      `/api/market-sim/paper/deployments/${encodeURIComponent(deploymentId)}/drift-review`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },

  paperDeploymentKillSwitch(
    deploymentId: string,
    armed = true,
    reason = "",
  ): Promise<{ deployment: MarketSimPaperDeployment }> {
    const q = new URLSearchParams({
      armed: armed ? "true" : "false",
      reason,
    });
    return request(
      `/api/market-sim/paper/deployments/${encodeURIComponent(deploymentId)}/kill-switch?${q}`,
      { method: "POST" },
    );
  },

  listPaperSessions(): Promise<{ sessions: Array<Record<string, unknown>> }> {
    return request("/api/market-sim/paper/sessions");
  },

  listPortfolios(limit = 50): Promise<{ portfolios: PaperPortfolio[] }> {
    return request(`/api/market-sim/portfolios?limit=${limit}`);
  },

  createPortfolio(payload: {
    name: string;
    initialEquity?: number;
    baseCurrency?: string;
    brokerMode?: string;
    providerId?: string;
    benchmarkSymbol?: string;
    orchestraId?: string | null;
    shortingEnabled?: boolean;
    settings?: Record<string, unknown>;
    agentAllocations?: Array<Record<string, unknown>>;
    strategyAllocations?: Array<Record<string, unknown>>;
    allowManualOnly?: boolean;
  }): Promise<{ portfolio: PaperPortfolio }> {
    return request("/api/market-sim/portfolios", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getPortfolio(portfolioId: string): Promise<{ portfolio: PaperPortfolio }> {
    return request(`/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}`);
  },

  fundPortfolio(
    portfolioId: string,
    payload: {
      delta: number;
      reason: string;
      idempotencyKey: string;
      operatorId?: string | null;
      kind?: string | null;
    },
  ): Promise<{
    portfolio: PaperPortfolio;
    funding: Record<string, unknown>;
    truth: Record<string, unknown>;
  }> {
    return request(`/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/funding`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  patchPortfolio(
    portfolioId: string,
    payload: {
      name?: string;
      orchestraId?: string | null;
      benchmarkSymbol?: string;
      settings?: Record<string, unknown>;
    },
  ): Promise<{ portfolio: PaperPortfolio }> {
    return request(`/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  startPortfolio(portfolioId: string): Promise<{ portfolio: PaperPortfolio }> {
    return request(`/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/start`, {
      method: "POST",
    });
  },

  pausePortfolio(portfolioId: string): Promise<{ portfolio: PaperPortfolio }> {
    return request(`/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/pause`, {
      method: "POST",
    });
  },

  resumePortfolio(portfolioId: string): Promise<{ portfolio: PaperPortfolio }> {
    return request(`/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/resume`, {
      method: "POST",
    });
  },

  stopPortfolio(portfolioId: string): Promise<{ portfolio: PaperPortfolio }> {
    return request(`/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/stop`, {
      method: "POST",
    });
  },

  portfolioDashboard(portfolioId: string, range = "YTD"): Promise<PortfolioDashboard> {
    return request(
      `/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/dashboard?range=${encodeURIComponent(range)}`,
    );
  },

  portfolioPerformance(
    portfolioId: string,
    range = "YTD",
  ): Promise<{ performance: Record<string, unknown> }> {
    return request(
      `/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/performance?range=${encodeURIComponent(range)}`,
    );
  },

  placePortfolioOrder(
    portfolioId: string,
    payload: {
      symbol: string;
      side: string;
      qty: number;
      clientOrderId?: string;
      agentId?: string;
      orchestraId?: string;
      strategyId?: string;
      strategyVersion?: number;
      decisionId?: string;
    },
  ): Promise<Record<string, unknown>> {
    return request(`/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/orders`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listPortfolioOrders(
    portfolioId: string,
    limit = 50,
  ): Promise<{ orders: Array<Record<string, unknown>> }> {
    return request(
      `/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/orders?limit=${limit}`,
    );
  },

  closePortfolioPosition(portfolioId: string, positionId: string): Promise<Record<string, unknown>> {
    return request(
      `/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/positions/${encodeURIComponent(positionId)}/close`,
      { method: "POST" },
    );
  },

  closeSelectedPortfolioPositions(
    portfolioId: string,
    positionIds: string[],
  ): Promise<Record<string, unknown>> {
    return request(
      `/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/positions/close-selected`,
      { method: "POST", body: JSON.stringify({ positionIds }) },
    );
  },

  flattenPortfolio(portfolioId: string): Promise<Record<string, unknown>> {
    return request(`/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/flatten`, {
      method: "POST",
      body: JSON.stringify({}),
    });
  },

  portfolioKillSwitch(portfolioId: string, armed = true): Promise<{ portfolio: PaperPortfolio }> {
    const q = new URLSearchParams({ armed: armed ? "true" : "false" });
    return request(`/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/kill-switch?${q}`, {
      method: "POST",
    });
  },

  createQualificationRun(body: Record<string, unknown>): Promise<Record<string, unknown>> {
    return request(`/api/market-sim/qualification-runs`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  getQualificationRun(qualificationId: string): Promise<Record<string, unknown>> {
    return request(`/api/market-sim/qualification-runs/${encodeURIComponent(qualificationId)}`);
  },

  getQualificationGates(qualificationId: string): Promise<Record<string, unknown>> {
    return request(
      `/api/market-sim/qualification-runs/${encodeURIComponent(qualificationId)}/gates`,
    );
  },

  cancelQualificationRun(qualificationId: string): Promise<Record<string, unknown>> {
    return request(
      `/api/market-sim/qualification-runs/${encodeURIComponent(qualificationId)}/cancel`,
      { method: "POST", body: JSON.stringify({}) },
    );
  },

  getDatasetCertification(
    datasetId: string,
    version?: string,
  ): Promise<Record<string, unknown>> {
    const q = version ? `?version=${encodeURIComponent(version)}` : "";
    return request(
      `/api/market-sim/datasets/${encodeURIComponent(datasetId)}/certification${q}`,
    );
  },

  evaluateDatasetCertification(
    datasetId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    return request(
      `/api/market-sim/datasets/${encodeURIComponent(datasetId)}/certification/evaluate`,
      { method: "POST", body: JSON.stringify(body) },
    );
  },

  getPortfolioStrategyRisk(portfolioId: string): Promise<Record<string, unknown>> {
    return request(
      `/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/strategy-risk`,
    );
  },

  getPaperExecutionCalibration(deploymentId: string): Promise<Record<string, unknown>> {
    return request(
      `/api/market-sim/paper-deployments/${encodeURIComponent(deploymentId)}/execution-calibration`,
    );
  },

  fetchMarketBars(params: {
    symbol: string;
    providerId?: string;
    timeframe?: string;
    limit?: number;
  }): Promise<MarketBarsResponse> {
    const q = new URLSearchParams({
      symbol: params.symbol,
      providerId: params.providerId || "binance_public",
      timeframe: params.timeframe || "1h",
      limit: String(params.limit ?? 200),
    });
    return request(`/api/market-sim/market/bars?${q}`);
  },

  savePortfolioAllocations(
    portfolioId: string,
    allocations: Array<Record<string, unknown>>,
  ): Promise<Record<string, unknown>> {
    return request(`/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/allocations`, {
      method: "POST",
      body: JSON.stringify({ allocations }),
    });
  },

  portfolioRebalancePreview(
    portfolioId: string,
    orders?: Array<Record<string, unknown>>,
  ): Promise<Record<string, unknown>> {
    return request(`/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/rebalance/preview`, {
      method: "POST",
      body: JSON.stringify({ orders: orders ?? null }),
    });
  },

  portfolioRebalanceExecute(
    portfolioId: string,
    orders?: Array<Record<string, unknown>>,
  ): Promise<Record<string, unknown>> {
    return request(`/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/rebalance/execute`, {
      method: "POST",
      body: JSON.stringify({ orders: orders ?? null }),
    });
  },

  exportPortfolio(portfolioId: string, format: "json" | "csv" = "json"): Promise<Record<string, unknown>> {
    return request(
      `/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/export?format=${format}`,
    );
  },

  portfolioTick(portfolioId: string): Promise<Record<string, unknown>> {
    return request(`/api/market-sim/portfolios/${encodeURIComponent(portfolioId)}/tick`, {
      method: "POST",
    });
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

  ...marketSimLabApi,
  ...researchCommandApi,

  // --- Trade orchestras / trading agents ---

  tradeOrchestraSummary(): Promise<TradeOrchestraSummary> {
    return request("/api/market-sim/orchestras/summary");
  },

  listTradeOrchestras(includeArchived = false): Promise<{ orchestras: TradeOrchestra[] }> {
    return request(`/api/market-sim/orchestras?includeArchived=${includeArchived ? "true" : "false"}`);
  },

  getTradeOrchestra(orchestraId: string): Promise<{ orchestra: TradeOrchestra }> {
    return request(`/api/market-sim/orchestras/${encodeURIComponent(orchestraId)}`);
  },

  createTradeOrchestra(payload: {
    name: string;
    description?: string;
    mandate?: Record<string, unknown>;
    memberAgentIds?: string[];
    seedRoles?: string[];
  }): Promise<{ orchestra: TradeOrchestra }> {
    return request("/api/market-sim/orchestras", { method: "POST", body: JSON.stringify(payload) });
  },

  updateTradeMandate(
    orchestraId: string,
    mandate: Record<string, unknown>,
    approvalId?: string,
  ): Promise<{ orchestra: TradeOrchestra }> {
    return request(`/api/market-sim/orchestras/${encodeURIComponent(orchestraId)}/mandate`, {
      method: "PUT",
      body: JSON.stringify({ mandate, approvalId }),
    });
  },

  setTradeAutonomy(orchestraId: string, level: string, approvalId?: string): Promise<{ orchestra: TradeOrchestra }> {
    return request(`/api/market-sim/orchestras/${encodeURIComponent(orchestraId)}/autonomy`, {
      method: "POST",
      body: JSON.stringify({ level, approvalId }),
    });
  },

  launchTradeMission(
    orchestraId: string,
    payload: { kind: string; asOf?: string; request?: string; priority?: string; dryRun?: boolean },
  ): Promise<{ mission: AgentMission }> {
    return request(`/api/market-sim/orchestras/${encodeURIComponent(orchestraId)}/missions`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listTradeMissions(orchestraId: string, limit = 50): Promise<{ missions: AgentMission[] }> {
    return request(`/api/market-sim/orchestras/${encodeURIComponent(orchestraId)}/missions?limit=${limit}`);
  },

  listTradingDecisions(params: {
    orchestraId?: string;
    missionId?: string;
    stage?: string;
    limit?: number;
  } = {}): Promise<{ decisions: TradingDecision[] }> {
    const q = new URLSearchParams();
    if (params.orchestraId) q.set("orchestraId", params.orchestraId);
    if (params.missionId) q.set("missionId", params.missionId);
    if (params.stage) q.set("stage", params.stage);
    q.set("limit", String(params.limit ?? 200));
    return request(`/api/market-sim/decisions?${q.toString()}`);
  },

  listTradingNewsFeeds(): Promise<{ feeds: TradingNewsFeed[] }> {
    return request("/api/market-sim/news/feeds");
  },

  createTradingNewsFeed(payload: {
    name: string;
    url: string;
    kind?: string;
    enabled?: boolean;
    declaredLatencySeconds?: number;
    licenseState?: string;
    symbolsHint?: string[];
  }): Promise<{ feed: TradingNewsFeed }> {
    return request("/api/market-sim/news/feeds", { method: "POST", body: JSON.stringify(payload) });
  },

  updateTradingNewsFeed(feedId: string, payload: Partial<TradingNewsFeed>): Promise<{ feed: TradingNewsFeed }> {
    return request(`/api/market-sim/news/feeds/${encodeURIComponent(feedId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  deleteTradingNewsFeed(feedId: string): Promise<{ feedId: string; deleted: boolean }> {
    return request(`/api/market-sim/news/feeds/${encodeURIComponent(feedId)}`, { method: "DELETE" });
  },

  pollTradingNews(feedId?: string): Promise<Record<string, unknown>> {
    return request("/api/market-sim/news/poll", { method: "POST", body: JSON.stringify({ feedId: feedId ?? null }) });
  },

  listTradingNewsItems(params: { asOf?: string; feedId?: string; limit?: number } = {}): Promise<{ items: TradingNewsItem[] }> {
    const q = new URLSearchParams();
    if (params.asOf) q.set("asOf", params.asOf);
    if (params.feedId) q.set("feedId", params.feedId);
    q.set("limit", String(params.limit ?? 100));
    return request(`/api/market-sim/news/items?${q.toString()}`);
  },

  listTradingNewsSignals(params: { asOf?: string; instrument?: string; limit?: number } = {}): Promise<{ signals: TradingNewsSignal[] }> {
    const q = new URLSearchParams();
    if (params.asOf) q.set("asOf", params.asOf);
    if (params.instrument) q.set("instrument", params.instrument);
    q.set("limit", String(params.limit ?? 100));
    return request(`/api/market-sim/news/signals?${q.toString()}`);
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

  getStartupRegistration(): Promise<{
    startup: {
      platform: string;
      supported: boolean;
      desired: boolean;
      registered: boolean | null;
      status: string;
      detail: string;
      launch_command?: string | null;
    };
    setting_key: string;
    truth?: Record<string, boolean>;
  }> {
    return request("/api/settings/startup-registration");
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

  patchBehaviorProfile(values: Record<string, unknown>): Promise<{
    profile: Record<string, unknown>;
    effective: Record<string, unknown>;
  }> {
    return request("/api/settings/behavior-profile", {
      method: "PATCH",
      body: JSON.stringify({ values }),
    });
  },

  previewBehaviorProfile(payload: {
    latest_user_message?: string;
    recent_user_messages?: string[];
  }): Promise<{
    language: Record<string, unknown>;
    behavior: Record<string, unknown>;
    system_prompt_digest: string;
    snapshot_hash: string;
  }> {
    return request("/api/settings/behavior-profile/preview", {
      method: "POST",
      body: JSON.stringify(payload),
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

  brainCatalog(cursor: import("../pages/brain/brain-catalog").CatalogCursor, signal?: AbortSignal): Promise<import("../pages/brain/brain-catalog").BrainCatalogPage> {
    return request(`/api/brain/catalog?source=${cursor.source}&offset=${cursor.offset}&limit=50`, { signal });
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

  listAgentSignals(opts?: {
    agentId?: string;
    senderId?: string;
    recipientId?: string;
    missionId?: string;
    runId?: string;
    traceId?: string;
    signalType?: string;
    priority?: string;
    status?: string;
    correlationId?: string;
    limit?: number;
    offset?: number;
  }): Promise<{ signals: AgentSignal[]; enabled?: boolean; truth?: Record<string, boolean> }> {
    const params = new URLSearchParams();
    if (opts?.agentId) params.set("agentId", opts.agentId);
    if (opts?.senderId) params.set("senderId", opts.senderId);
    if (opts?.recipientId) params.set("recipientId", opts.recipientId);
    if (opts?.missionId) params.set("missionId", opts.missionId);
    if (opts?.runId) params.set("runId", opts.runId);
    if (opts?.traceId) params.set("traceId", opts.traceId);
    if (opts?.signalType) params.set("signalType", opts.signalType);
    if (opts?.priority) params.set("priority", opts.priority);
    if (opts?.status) params.set("status", opts.status);
    if (opts?.correlationId) params.set("correlationId", opts.correlationId);
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    if (opts?.offset != null) params.set("offset", String(opts.offset));
    const q = params.toString();
    return request(`/api/agents/signals${q ? `?${q}` : ""}`);
  },

  getAgentSignal(signalId: string): Promise<{ signal: AgentSignal }> {
    return request(`/api/agents/signals/${encodeURIComponent(signalId)}`);
  },

  listAgentSignalDeliveries(
    signalId: string,
    opts?: { limit?: number },
  ): Promise<{ deliveries: AgentSignalDelivery[] }> {
    const params = new URLSearchParams();
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    const q = params.toString();
    return request(`/api/agents/signals/${encodeURIComponent(signalId)}/deliveries${q ? `?${q}` : ""}`);
  },

  getAgentSignalChain(
    signalId: string,
    opts?: { depth?: number; limit?: number },
  ): Promise<SignalCausalChain> {
    const params = new URLSearchParams();
    if (opts?.depth != null) params.set("depth", String(opts.depth));
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    const q = params.toString();
    return request(`/api/agents/signals/${encodeURIComponent(signalId)}/chain${q ? `?${q}` : ""}`);
  },

  getAgentSignalMetrics(opts?: {
    windowMinutes?: number;
  }): Promise<{ enabled?: boolean; metrics: AgentSignalMetrics; truth?: Record<string, boolean> }> {
    const params = new URLSearchParams();
    if (opts?.windowMinutes != null) params.set("windowMinutes", String(opts.windowMinutes));
    const q = params.toString();
    return request(`/api/agents/signals/metrics${q ? `?${q}` : ""}`);
  },

  getAgentSignalGraph(opts?: {
    windowHours?: number;
    missionId?: string;
  }): Promise<{
    enabled?: boolean;
    graph: AgentCommunicationGraph;
    truth?: Record<string, boolean>;
  }> {
    const params = new URLSearchParams();
    if (opts?.windowHours != null) params.set("windowHours", String(opts.windowHours));
    if (opts?.missionId) params.set("missionId", opts.missionId);
    const q = params.toString();
    return request(`/api/agents/signals/graph${q ? `?${q}` : ""}`);
  },

  listAgentSignalDeadLetters(opts?: {
    limit?: number;
    offset?: number;
  }): Promise<{ deadLetters: AgentSignalDeadLetter[]; enabled?: boolean }> {
    const params = new URLSearchParams();
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    if (opts?.offset != null) params.set("offset", String(opts.offset));
    const q = params.toString();
    return request(`/api/agents/signals/dead-letters${q ? `?${q}` : ""}`);
  },

  retryAgentSignalDeadLetter(
    deadLetterId: string,
  ): Promise<{ delivery: AgentSignalDelivery }> {
    return request(`/api/agents/signals/dead-letters/${encodeURIComponent(deadLetterId)}/retry`, {
      method: "POST",
    });
  },

  listSignalsForAgent(
    agentId: string,
    opts?: { limit?: number },
  ): Promise<{
    signals: AgentSignal[];
    stats: AgentSignalStats;
    enabled?: boolean;
  }> {
    const params = new URLSearchParams();
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    const q = params.toString();
    return request(`/api/agents/${encodeURIComponent(agentId)}/signals${q ? `?${q}` : ""}`);
  },

  listSignalsForMission(
    missionId: string,
    opts?: { limit?: number },
  ): Promise<{ signals: AgentSignal[]; enabled?: boolean }> {
    const params = new URLSearchParams();
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    const q = params.toString();
    return request(`/api/agents/missions/${encodeURIComponent(missionId)}/signals${q ? `?${q}` : ""}`);
  },

  publishAgentSignal(payload: Record<string, unknown>): Promise<{ signal: AgentSignal }> {
    return request("/api/agents/signals", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  ackAgentSignal(
    signalId: string,
    payload?: { deliveryId?: string; consumer?: string },
  ): Promise<{ acknowledged: AgentSignalDelivery[] }> {
    return request(`/api/agents/signals/${encodeURIComponent(signalId)}/ack`, {
      method: "POST",
      body: JSON.stringify(payload ?? {}),
    });
  },

  reconcileAgents(): Promise<{ updated: string[]; count: number }> {
    return request("/api/agents/reconcile", { method: "POST" });
  },

  getAgentsDashboard(opts?: {
    windowHours?: number;
    failureWindowHours?: number;
  }): Promise<AgentsDashboard> {
    const params = new URLSearchParams();
    if (opts?.windowHours != null) params.set("windowHours", String(opts.windowHours));
    if (opts?.failureWindowHours != null) {
      params.set("failureWindowHours", String(opts.failureWindowHours));
    }
    const q = params.toString();
    return request(`/api/agents/dashboard${q ? `?${q}` : ""}`);
  },

  fleetStartAll(): Promise<FleetBulkResult> {
    return request("/api/agents/fleet/start-all", { method: "POST" });
  },

  fleetPauseAll(): Promise<FleetBulkResult> {
    return request("/api/agents/fleet/pause-all", { method: "POST" });
  },

  /* ---------- Worker registry ---------- */

  listWorkers(opts?: { pool?: string }): Promise<WorkersListResponse> {
    const params = new URLSearchParams();
    if (opts?.pool) params.set("pool", opts.pool);
    const q = params.toString();
    return request(`/api/workers${q ? `?${q}` : ""}`);
  },

  getWorkersDashboard(): Promise<WorkerFabricDashboard> {
    return request("/api/workers/dashboard");
  },

  getWorker(workerId: string): Promise<{ worker: WorkerFabricWorker; pool?: WorkerFabricPool | null }> {
    return request(`/api/workers/${encodeURIComponent(workerId)}`);
  },

  listWorkerPools(): Promise<{
    pools: WorkerPoolDefinition[];
    provider_io?: Record<string, unknown>;
  }> {
    return request("/api/workers/pools");
  },

  scaleWorkerPool(poolId: string, desiredCount: number): Promise<WorkerPoolScaleResponse> {
    return request(`/api/workers/pools/${encodeURIComponent(poolId)}/scale`, {
      method: "POST",
      body: JSON.stringify({ desiredCount }),
    });
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

  analyticsDashboard(opts?: {
    chartRange?: string;
    rankingRange?: string;
    activityLimit?: number;
  }): Promise<{ dashboard: AnalyticsDashboard }> {
    const chartRange = opts?.chartRange ?? "30d";
    const rankingRange = opts?.rankingRange ?? "7d";
    const activityLimit = opts?.activityLimit ?? 10;
    const q = new URLSearchParams({
      chartRange,
      rankingRange,
      activityLimit: String(activityLimit),
    });
    return request(`/api/analytics/dashboard?${q.toString()}`);
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
    if (filters?.taskType) params.set("taskType", filters.taskType);
    if (filters?.operationalStatus) params.set("operationalStatus", filters.operationalStatus);
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
