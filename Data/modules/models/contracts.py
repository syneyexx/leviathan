"""Model Control Plane contracts — normalized public types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class ModelSource(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"
    API = "api"
    DOWNLOADED = "downloaded"
    IMPORTED = "imported"
    TRAINED = "trained"


class ModelLifecycleState(str, Enum):
    UNKNOWN = "unknown"
    DISCOVERED = "discovered"
    AVAILABLE = "available"
    IMPORTING = "importing"
    DOWNLOADING = "downloading"
    VALIDATING = "validating"
    LOADING = "loading"
    LOADED = "loaded"
    ACTIVE = "active"
    UNLOADING = "unloading"
    OFFLINE = "offline"
    ERROR = "error"


class ModelHealthState(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    ERROR = "error"


class CapabilityState(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    UNVERIFIED = "unverified"
    UNMEASURED = "unmeasured"


class ProviderHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    AUTH_ERROR = "auth_error"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class DownloadState(str, Enum):
    QUEUED = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    PAUSED = "PAUSED"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PreflightVerdict(str, Enum):
    SAFE = "SAFE"
    WARNING = "WARNING"
    LIKELY_OOM = "LIKELY_OOM"
    UNKNOWN = "UNKNOWN"


CapabilityName = Literal[
    "chat",
    "reasoning",
    "coding",
    "toolCalling",
    "structuredOutput",
    "vision",
    "embeddings",
    "streaming",
]


@dataclass(frozen=True)
class RuntimeCapabilities:
    discover_models: bool = True
    import_model: bool = False
    download_model: bool = False
    load_model: bool = False
    unload_model: bool = False
    delete_model: bool = False
    list_loaded_models: bool = False
    inference: bool = True
    streaming: bool = True
    embeddings: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    vision: bool = False
    runtime_metrics: bool = False
    load_options: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "discoverModels": self.discover_models,
            "importModel": self.import_model,
            "downloadModel": self.download_model,
            "loadModel": self.load_model,
            "unloadModel": self.unload_model,
            "deleteModel": self.delete_model,
            "listLoadedModels": self.list_loaded_models,
            "inference": self.inference,
            "streaming": self.streaming,
            "embeddings": self.embeddings,
            "toolCalling": self.tool_calling,
            "structuredOutput": self.structured_output,
            "vision": self.vision,
            "runtimeMetrics": self.runtime_metrics,
            "loadOptions": list(self.load_options),
        }


@dataclass
class ModelCapabilities:
    chat: CapabilityState = CapabilityState.UNKNOWN
    reasoning: CapabilityState = CapabilityState.UNKNOWN
    coding: CapabilityState = CapabilityState.UNKNOWN
    tool_calling: CapabilityState = CapabilityState.UNKNOWN
    structured_output: CapabilityState = CapabilityState.UNKNOWN
    vision: CapabilityState = CapabilityState.UNKNOWN
    embeddings: CapabilityState = CapabilityState.UNKNOWN
    streaming: CapabilityState = CapabilityState.UNKNOWN

    def public_dict(self) -> dict[str, Any]:
        return {
            "chat": self.chat.value,
            "reasoning": self.reasoning.value,
            "coding": self.coding.value,
            "toolCalling": self.tool_calling.value,
            "structuredOutput": self.structured_output.value,
            "vision": self.vision.value,
            "embeddings": self.embeddings.value,
            "streaming": self.streaming.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ModelCapabilities":
        data = data or {}

        def read(key: str, alt: str | None = None) -> CapabilityState:
            raw = data.get(key)
            if raw is None and alt:
                raw = data.get(alt)
            if raw is None:
                return CapabilityState.UNKNOWN
            try:
                return CapabilityState(str(raw))
            except ValueError:
                return CapabilityState.UNKNOWN

        return cls(
            chat=read("chat"),
            reasoning=read("reasoning"),
            coding=read("coding"),
            tool_calling=read("toolCalling", "tool_calling"),
            structured_output=read("structuredOutput", "structured_output"),
            vision=read("vision"),
            embeddings=read("embeddings"),
            streaming=read("streaming"),
        )


@dataclass
class ModelDescriptor:
    id: str
    display_name: str
    provider_id: str
    source: ModelSource
    capabilities: ModelCapabilities
    lifecycle_state: ModelLifecycleState = ModelLifecycleState.DISCOVERED
    health: ModelHealthState = ModelHealthState.UNKNOWN
    active: bool = False
    loaded: bool | None = None
    runtime_id: str | None = None
    object_type: str | None = None
    architecture: str | None = None
    family: str | None = None
    parameter_count: int | None = None
    quantization: str | None = None
    format: str | None = None
    disk_size_bytes: int | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
    local_path: str | None = None
    endpoint: str | None = None
    last_discovered_at: str | None = None
    last_used_at: str | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "displayName": self.display_name,
            "providerId": self.provider_id,
            "runtimeId": self.runtime_id,
            "source": self.source.value,
            "objectType": self.object_type,
            "architecture": self.architecture,
            "family": self.family,
            "parameterCount": self.parameter_count,
            "quantization": self.quantization,
            "format": self.format,
            "diskSizeBytes": self.disk_size_bytes,
            "contextWindow": self.context_window,
            "maxOutputTokens": self.max_output_tokens,
            "capabilities": self.capabilities.public_dict(),
            "lifecycleState": self.lifecycle_state.value,
            "health": self.health.value,
            "active": self.active,
            "loaded": self.loaded,
            "localPath": self.local_path,
            "endpoint": self.endpoint,
            "lastDiscoveredAt": self.last_discovered_at,
            "lastUsedAt": self.last_used_at,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }


@dataclass
class ModelProfile:
    model_id: str
    temperature: float = 0.7
    top_p: float = 0.95
    top_k: int = 40
    max_tokens: int = 2048
    repeat_penalty: float = 1.05
    seed: int = -1
    system_prompt: str = ""
    active: bool = False
    updated_at: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "temperature": self.temperature,
            "topP": self.top_p,
            "topK": self.top_k,
            "maxTokens": self.max_tokens,
            "repeatPenalty": self.repeat_penalty,
            "seed": self.seed,
            "systemPrompt": self.system_prompt,
            "active": self.active,
            "updatedAt": self.updated_at,
        }


@dataclass(frozen=True)
class LoadOptions:
    context_length: int | None = None
    gpu_offload_layers: int | None = None
    gpu_memory_limit_bytes: int | None = None
    cpu_threads: int | None = None
    batch_size: int | None = None
    flash_attention: bool | None = None

    def as_provider_payload(self, allowed: tuple[str, ...] | list[str]) -> dict[str, Any]:
        mapping = {
            "contextLength": self.context_length,
            "gpuOffloadLayers": self.gpu_offload_layers,
            "gpuMemoryLimitBytes": self.gpu_memory_limit_bytes,
            "cpuThreads": self.cpu_threads,
            "batchSize": self.batch_size,
            "flashAttention": self.flash_attention,
        }
        return {k: v for k, v in mapping.items() if k in allowed and v is not None}


@dataclass
class ProviderRecord:
    provider_id: str
    name: str
    provider_type: str
    endpoint: str
    enabled: bool = True
    health: ProviderHealth = ProviderHealth.UNKNOWN
    api_key_configured: bool = False
    auto_connect: bool = True
    timeout_seconds: float = 30.0
    refresh_interval_seconds: float = 60.0
    last_successful_at: str | None = None
    last_error: str | None = None
    last_latency_ms: float | None = None
    last_check_at: str | None = None
    capabilities: RuntimeCapabilities = field(default_factory=RuntimeCapabilities)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.provider_id,
            "name": self.name,
            "type": self.provider_type,
            "endpoint": self.endpoint,
            "enabled": self.enabled,
            "health": self.health.value,
            "apiKeyConfigured": self.api_key_configured,
            "autoConnect": self.auto_connect,
            "timeoutSeconds": self.timeout_seconds,
            "refreshIntervalSeconds": self.refresh_interval_seconds,
            "lastSuccessfulAt": self.last_successful_at,
            "lastError": self.last_error,
            "lastLatencyMs": self.last_latency_ms,
            "lastCheckAt": self.last_check_at,
            "capabilities": self.capabilities.public_dict(),
            "metadata": dict(self.metadata),
        }


@dataclass
class RouterConfig:
    fallback_order: list[str] = field(default_factory=list)
    role_overrides: dict[str, str] = field(default_factory=dict)
    cloud_fallback_allowed: bool = False
    streaming: bool = True
    stream_provisional_text: bool = True
    progress_events_enabled: bool = True

    def public_dict(self) -> dict[str, Any]:
        return {
            "fallbackOrder": list(self.fallback_order),
            "roleModelOverrides": dict(self.role_overrides),
            "cloudFallbackAllowed": self.cloud_fallback_allowed,
            "streaming": self.streaming,
            "streamProvisionalText": self.stream_provisional_text,
            "progressEventsEnabled": self.progress_events_enabled,
        }


@dataclass
class RuntimeCapacity:
    global_limit: int | None
    global_inflight: int = 0
    provider_limits: dict[str, int | None] = field(default_factory=dict)
    model_limits: dict[str, int | None] = field(default_factory=dict)
    queue_depth: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "globalLimit": self.global_limit,
            "globalInflight": self.global_inflight,
            "providerLimits": dict(self.provider_limits),
            "modelLimits": dict(self.model_limits),
            "queueDepth": self.queue_depth,
        }


@dataclass
class GatewaySnapshot:
    models_in_use: list[str]
    active_calls: int
    queue_depth: int
    capacity: RuntimeCapacity
    last_fallback_reason: str | None
    calls_failed: int
    capacity_timeouts: int
    last_error: str | None
    last_selected_model: str | None = None
    last_trace_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "modelsInUse": list(self.models_in_use),
            "activeCalls": self.active_calls,
            "queueDepth": self.queue_depth,
            "capacity": self.capacity.public_dict(),
            "lastFallbackReason": self.last_fallback_reason,
            "callsFailed": self.calls_failed,
            "capacityTimeouts": self.capacity_timeouts,
            "lastError": self.last_error,
            "lastSelectedModel": self.last_selected_model,
            "lastTraceId": self.last_trace_id,
        }


@dataclass(frozen=True)
class ModelRequest:
    required_capabilities: tuple[str, ...] = ()
    preferred_role: str | None = None
    locality: str = "local_preferred"
    explicit_model_id: str | None = None
    agent_model_id: str | None = None
    job_class: str = "INTERACTIVE"  # INTERACTIVE | BACKGROUND | BATCH (U033)


@dataclass
class RouteDecision:
    model_id: str
    reason: str
    fallback_used: bool = False
    fallback_reason: str | None = None
    candidates_tried: list[str] = field(default_factory=list)
    trace_id: str | None = None
    # Wave 3 measured routing (U041–U042)
    job_class: str | None = None
    candidate_scores: list[dict[str, Any]] = field(default_factory=list)
    policy_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "reason": self.reason,
            "fallbackUsed": self.fallback_used,
            "fallbackReason": self.fallback_reason,
            "candidatesTried": list(self.candidates_tried),
            "traceId": self.trace_id,
            "jobClass": self.job_class,
            "candidateScores": list(self.candidate_scores),
            "policyId": self.policy_id,
            "truth": {
                "selection_is_not_permission": True,
                "router_does_not_grant_capability_authority": True,
            },
        }


@dataclass
class VerifiedCapability:
    capability: str
    declared: CapabilityState
    verified: CapabilityState
    last_tested_at: str | None = None
    detail: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "declared": self.declared.value,
            "verified": self.verified.value,
            "lastTestedAt": self.last_tested_at,
            "detail": self.detail,
        }


@dataclass
class DownloadJob:
    download_id: str
    state: DownloadState
    source: str
    repository_id: str | None = None
    revision: str | None = None
    destination: str | None = None
    bytes_downloaded: int | None = None
    total_bytes: int | None = None
    speed_bps: float | None = None
    eta_seconds: float | None = None
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    model_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        progress_percent = None
        if (
            self.bytes_downloaded is not None
            and self.total_bytes is not None
            and self.total_bytes > 0
        ):
            progress_percent = round(100.0 * self.bytes_downloaded / self.total_bytes, 2)
        return {
            "id": self.download_id,
            "state": self.state.value,
            "source": self.source,
            "repositoryId": self.repository_id,
            "revision": self.revision,
            "destination": self.destination,
            "bytesDownloaded": self.bytes_downloaded,
            "totalBytes": self.total_bytes,
            "progressPercent": progress_percent,
            "speedBps": self.speed_bps,
            "etaSeconds": self.eta_seconds,
            "error": self.error,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "modelId": self.model_id,
        }


@dataclass(frozen=True)
class PreflightResult:
    verdict: PreflightVerdict
    reasons: tuple[str, ...] = ()
    estimated: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "reasons": list(self.reasons),
            "estimated": self.estimated,
            "details": dict(self.details),
        }


# --- Residency / runtime binding (One-Brain model runtime) ---


class ResidencyState(str, Enum):
    """Detailed physical residency — maps onto ModelLifecycleState where needed."""

    UNLOADED = "UNLOADED"
    STARTING = "STARTING"
    LOADING = "LOADING"
    READY = "READY"
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    DRAINING = "DRAINING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"
    EXTERNAL = "EXTERNAL"
    UNAVAILABLE = "UNAVAILABLE"


class PhysicalPlacement(str, Enum):
    """Where weights actually live. UNKNOWN unless placement is known."""

    GPU = "GPU"
    CPU = "CPU"
    HYBRID = "HYBRID"
    EXTERNAL = "EXTERNAL"
    UNKNOWN = "UNKNOWN"


class ResidencyPolicyKind(str, Enum):
    KEEP_HOT = "KEEP_HOT"
    IDLE_UNLOAD = "IDLE_UNLOAD"
    WARM_THEN_UNLOAD = "WARM_THEN_UNLOAD"  # only when backend truly supports demotion


class ServabilityState(str, Enum):
    SERVABLE = "SERVABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class ResourceProvenance(str, Enum):
    MEASURED = "MEASURED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


@dataclass
class ModelRuntimeBinding:
    """How a registry model is served — distinct from acquisition source."""

    model_id: str
    runtime_kind: str  # llama_cpp | vllm_class | lm_studio | ollama | openai_compatible | unknown
    runtime_provider_id: str | None = None
    backend_model_id: str | None = None
    local_path: str | None = None
    managed: bool = False
    servability_state: ServabilityState = ServabilityState.UNKNOWN
    servability_reason: str | None = None
    runtime_capabilities: RuntimeCapabilities | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "runtimeKind": self.runtime_kind,
            "runtimeProviderId": self.runtime_provider_id,
            "backendModelId": self.backend_model_id,
            "localPath": self.local_path,
            "managed": self.managed,
            "servabilityState": self.servability_state.value,
            "servabilityReason": self.servability_reason,
            "runtimeCapabilities": (
                self.runtime_capabilities.public_dict() if self.runtime_capabilities else None
            ),
            "metadata": dict(self.metadata),
        }


@dataclass
class ResidencyPolicy:
    """Per-model residency policy — distinct from ModelProfile."""

    model_id: str
    policy: ResidencyPolicyKind = ResidencyPolicyKind.IDLE_UNLOAD
    idle_unload_seconds: float = 300.0
    full_unload_seconds: float | None = None
    pinned: bool = False
    load_options: LoadOptions | None = None
    updated_at: str | None = None

    def public_dict(self) -> dict[str, Any]:
        opts = None
        if self.load_options is not None:
            opts = {
                "contextLength": self.load_options.context_length,
                "gpuOffloadLayers": self.load_options.gpu_offload_layers,
                "gpuMemoryLimitBytes": self.load_options.gpu_memory_limit_bytes,
                "cpuThreads": self.load_options.cpu_threads,
                "batchSize": self.load_options.batch_size,
                "flashAttention": self.load_options.flash_attention,
            }
        return {
            "modelId": self.model_id,
            "policy": self.policy.value,
            "idleUnloadSeconds": self.idle_unload_seconds,
            "fullUnloadSeconds": self.full_unload_seconds,
            "pinned": self.pinned,
            "loadOptions": opts,
            "updatedAt": self.updated_at,
        }


@dataclass
class ResidencyLease:
    """Live in-memory lease — never restored from SQLite after restart."""

    lease_id: str
    model_id: str
    consumer: str
    domain: str | None = None
    model_role: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    job_class: str = "INTERACTIVE"
    explicit_selection: bool = False
    acquired_at: float = 0.0
    last_activity_at: float = 0.0

    def public_dict(self) -> dict[str, Any]:
        return {
            "leaseId": self.lease_id,
            "modelId": self.model_id,
            "consumer": self.consumer,
            "domain": self.domain,
            "modelRole": self.model_role,
            "runId": self.run_id,
            "traceId": self.trace_id,
            "jobClass": self.job_class,
            "explicitSelection": self.explicit_selection,
            "acquiredAt": self.acquired_at,
            "lastActivityAt": self.last_activity_at,
        }


@dataclass
class ResourceEstimate:
    """Honest resource estimate with provenance — never fabricates zeros."""

    ram_needed_bytes: int | None = None
    ram_needed_provenance: ResourceProvenance = ResourceProvenance.UNKNOWN
    vram_needed_bytes: int | None = None
    vram_needed_provenance: ResourceProvenance = ResourceProvenance.UNKNOWN
    ram_available_bytes: int | None = None
    ram_available_provenance: ResourceProvenance = ResourceProvenance.UNKNOWN
    vram_available_bytes: int | None = None
    vram_available_provenance: ResourceProvenance = ResourceProvenance.UNKNOWN
    headroom_ram_bytes: int | None = None
    headroom_vram_bytes: int | None = None
    verdict: PreflightVerdict = PreflightVerdict.UNKNOWN
    reasons: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "ramNeededBytes": self.ram_needed_bytes,
            "ramNeededProvenance": self.ram_needed_provenance.value,
            "vramNeededBytes": self.vram_needed_bytes,
            "vramNeededProvenance": self.vram_needed_provenance.value,
            "ramAvailableBytes": self.ram_available_bytes,
            "ramAvailableProvenance": self.ram_available_provenance.value,
            "vramAvailableBytes": self.vram_available_bytes,
            "vramAvailableProvenance": self.vram_available_provenance.value,
            "headroomRamBytes": self.headroom_ram_bytes,
            "headroomVramBytes": self.headroom_vram_bytes,
            "verdict": self.verdict.value,
            "reasons": list(self.reasons),
            "details": dict(self.details),
            "truth": {
                "unknown_is_not_zero": True,
                "estimates_are_not_exact": True,
            },
        }


@dataclass
class ModelResidencySnapshot:
    model_id: str
    state: ResidencyState
    placement: PhysicalPlacement = PhysicalPlacement.UNKNOWN
    managed: bool = False
    worker_id: str | None = None
    pid: int | None = None
    endpoint: str | None = None
    active_lease_count: int = 0
    consumers: tuple[str, ...] = ()
    policy: ResidencyPolicy | None = None
    last_used_at: float | None = None
    idle_since: float | None = None
    next_action_at: float | None = None
    runtime_kind: str | None = None
    load_started_at: float | None = None
    ready_at: float | None = None
    last_error: str | None = None
    resource_estimate: ResourceEstimate | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "state": self.state.value,
            "placement": self.placement.value,
            "managed": self.managed,
            "workerId": self.worker_id,
            "pid": self.pid,
            "endpoint": self.endpoint,
            "activeLeaseCount": self.active_lease_count,
            "consumers": list(self.consumers),
            "policy": self.policy.public_dict() if self.policy else None,
            "lastUsedAt": self.last_used_at,
            "idleSince": self.idle_since,
            "nextActionAt": self.next_action_at,
            "runtimeKind": self.runtime_kind,
            "loadStartedAt": self.load_started_at,
            "readyAt": self.ready_at,
            "lastError": self.last_error,
            "resourceEstimate": (
                self.resource_estimate.public_dict() if self.resource_estimate else None
            ),
        }


@dataclass
class ResolvedModelTarget:
    """Stage-A logical resolution — does not load weights."""

    model: ModelDescriptor
    route: RouteDecision
    profile: ModelProfile
    provider_id: str
    runtime_binding: ModelRuntimeBinding | None
    backend_model_id: str
    endpoint: str
    api_key: str | None
    context_window: int | None
    managed: bool
    explicit_selection: bool
    required_capabilities: tuple[str, ...] = ()
    preferred_role: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "model": self.model.public_dict(),
            "route": self.route.public_dict(),
            "profile": self.profile.public_dict(),
            "providerId": self.provider_id,
            "runtimeBinding": (
                self.runtime_binding.public_dict() if self.runtime_binding else None
            ),
            "backendModelId": self.backend_model_id,
            "endpoint": self.endpoint,
            "contextWindow": self.context_window,
            "managed": self.managed,
            "explicitSelection": self.explicit_selection,
            "requiredCapabilities": list(self.required_capabilities),
            "preferredRole": self.preferred_role,
        }
