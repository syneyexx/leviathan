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


@dataclass
class RouteDecision:
    model_id: str
    reason: str
    fallback_used: bool = False
    fallback_reason: str | None = None
    candidates_tried: list[str] = field(default_factory=list)
    trace_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "reason": self.reason,
            "fallbackUsed": self.fallback_used,
            "fallbackReason": self.fallback_reason,
            "candidatesTried": list(self.candidates_tried),
            "traceId": self.trace_id,
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
        return {
            "id": self.download_id,
            "state": self.state.value,
            "source": self.source,
            "repositoryId": self.repository_id,
            "revision": self.revision,
            "destination": self.destination,
            "bytesDownloaded": self.bytes_downloaded,
            "totalBytes": self.total_bytes,
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
