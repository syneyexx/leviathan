"""LM Studio control-plane contracts: capabilities, load config compiler, errors.

LM Studio remains an externally owned runtime. Leviathan may discover, probe,
load, unload, estimate, and reconcile via official REST / CLI surfaces.
Leviathan must not kill or restart LM Studio.exe.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from Data.modules.models.contracts import LoadOptions
from Data.modules.models.errors import CAPABILITY_NOT_SUPPORTED, ModelControlError


class CapabilitySupport(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class CapabilityScope(str, Enum):
    LOAD = "LOAD"
    INFERENCE = "INFERENCE"
    PLACEMENT_POLICY = "PLACEMENT_POLICY"
    RUNTIME_POLICY = "RUNTIME_POLICY"


class CapabilityTransport(str, Enum):
    REST = "REST"
    CLI = "CLI"
    SDK = "SDK"
    LEVIATHAN = "LEVIATHAN"
    NONE = "NONE"


# Official native REST load body fields (LM Studio docs).
REST_LOAD_FIELDS = frozenset(
    {
        "model",
        "context_length",
        "eval_batch_size",
        "flash_attention",
        "num_experts",
        "offload_kv_cache_to_gpu",
        "echo_load_config",
    }
)

# CLI `lms load` documented flags used by Leviathan.
CLI_LOAD_FLAGS = frozenset({"gpu", "context-length", "estimate-only", "ttl", "identifier", "host"})

# Normalized LoadOptions keys that map to LM Studio surfaces.
LM_STUDIO_LOAD_OPTION_KEYS = (
    "contextLength",
    "batchSize",  # maps to eval_batch_size
    "flashAttention",
    "offloadKvCacheToGpu",
    "numExperts",
    "gpuOffloadRatio",
    "gpuSplitMode",
    "tensorSplit",
    "mainGpuOrdinal",
    "excludedDeviceIds",
    "gpuStrictVramCap",
    "kvCacheDtype",
    "continuousBatching",
    "prefixCache",
    "speculativeDecoding",
    "draftModelId",
    "speculativeTokens",
    "cpuThreads",
    "seed",
    "allowMultiGpu",
    "shardingMode",
    "keepDisplayHeadroom",
    "tensorParallelSize",
)


@dataclass(frozen=True)
class CapabilityField:
    """Authoritative per-control capability descriptor for Models UI / compiler."""

    key: str
    support: CapabilitySupport
    scope: CapabilityScope
    transport: CapabilityTransport
    reason_code: str | None = None
    note: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "support": self.support.value,
            "scope": self.scope.value,
            "transport": self.transport.value,
            "reasonCode": self.reason_code,
            "note": self.note,
        }


@dataclass(frozen=True)
class LMStudioControlCapabilities:
    """Per-field support for the connected LM Studio instance."""

    native_rest: CapabilitySupport = CapabilitySupport.UNKNOWN
    load: CapabilitySupport = CapabilitySupport.UNKNOWN
    unload: CapabilitySupport = CapabilitySupport.UNKNOWN
    loaded_instances: CapabilitySupport = CapabilitySupport.UNKNOWN
    resource_estimate: CapabilitySupport = CapabilitySupport.UNKNOWN
    gpu_ratio: CapabilitySupport = CapabilitySupport.UNKNOWN
    gpu_split: CapabilitySupport = CapabilitySupport.UNKNOWN
    custom_gpu_split: CapabilitySupport = CapabilitySupport.UNKNOWN
    disabled_gpus: CapabilitySupport = CapabilitySupport.UNKNOWN
    main_gpu: CapabilitySupport = CapabilitySupport.UNKNOWN
    strict_vram_cap: CapabilitySupport = CapabilitySupport.UNKNOWN
    flash_attention: CapabilitySupport = CapabilitySupport.UNKNOWN
    kv_gpu_offload: CapabilitySupport = CapabilitySupport.UNKNOWN
    kv_quantization: CapabilitySupport = CapabilitySupport.UNKNOWN
    eval_batch: CapabilitySupport = CapabilitySupport.UNKNOWN
    moe_num_experts: CapabilitySupport = CapabilitySupport.UNKNOWN
    mmap: CapabilitySupport = CapabilitySupport.UNKNOWN
    mlock: CapabilitySupport = CapabilitySupport.UNKNOWN
    continuous_batching: CapabilitySupport = CapabilitySupport.UNKNOWN
    speculative_decoding: CapabilitySupport = CapabilitySupport.UNKNOWN
    draft_model: CapabilitySupport = CapabilitySupport.UNKNOWN
    advanced_llama_overrides: CapabilitySupport = CapabilitySupport.UNKNOWN
    context_length: CapabilitySupport = CapabilitySupport.UNKNOWN
    echo_load_config: CapabilitySupport = CapabilitySupport.UNKNOWN
    seed: CapabilitySupport = CapabilitySupport.UNKNOWN
    cpu_threads: CapabilitySupport = CapabilitySupport.UNKNOWN
    provider_version: str | None = None
    cli_available: bool = False
    sdk_available: bool = False
    sdk_reachable: bool = False
    sdk_version: str | None = None
    rest_base: str | None = None
    notes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        fields = {
            k: v.value if isinstance(v, CapabilitySupport) else v
            for k, v in {
                "nativeRest": self.native_rest,
                "load": self.load,
                "unload": self.unload,
                "loadedInstances": self.loaded_instances,
                "resourceEstimate": self.resource_estimate,
                "gpuRatio": self.gpu_ratio,
                "gpuSplit": self.gpu_split,
                "customGpuSplit": self.custom_gpu_split,
                "disabledGpus": self.disabled_gpus,
                "mainGpu": self.main_gpu,
                "strictVramCap": self.strict_vram_cap,
                "flashAttention": self.flash_attention,
                "kvGpuOffload": self.kv_gpu_offload,
                "kvQuantization": self.kv_quantization,
                "evalBatch": self.eval_batch,
                "moeNumExperts": self.moe_num_experts,
                "mmap": self.mmap,
                "mlock": self.mlock,
                "continuousBatching": self.continuous_batching,
                "speculativeDecoding": self.speculative_decoding,
                "draftModel": self.draft_model,
                "advancedLlamaOverrides": self.advanced_llama_overrides,
                "contextLength": self.context_length,
                "echoLoadConfig": self.echo_load_config,
                "seed": self.seed,
                "cpuThreads": self.cpu_threads,
            }.items()
        }
        return {
            **fields,
            "providerVersion": self.provider_version,
            "cliAvailable": self.cli_available,
            "sdkAvailable": self.sdk_available,
            "sdkReachable": self.sdk_reachable,
            "sdkVersion": self.sdk_version,
            "restBase": self.rest_base,
            "notes": list(self.notes),
            "fields": [f.public_dict() for f in self.field_matrix()],
        }

    def field_support(self, field_name: str) -> CapabilitySupport:
        mapping = {
            "contextLength": self.context_length,
            "batchSize": self.eval_batch,
            "evalBatchSize": self.eval_batch,
            "flashAttention": self.flash_attention,
            "offloadKvCacheToGpu": self.kv_gpu_offload,
            "numExperts": self.moe_num_experts,
            "gpuOffloadRatio": self.gpu_ratio,
            "gpuSplitMode": self.gpu_split,
            "tensorSplit": self.custom_gpu_split,
            "mainGpuOrdinal": self.main_gpu,
            "excludedDeviceIds": self.disabled_gpus,
            "gpuStrictVramCap": self.strict_vram_cap,
            "kvCacheDtype": self.kv_quantization,
            "continuousBatching": self.continuous_batching,
            "prefixCache": CapabilitySupport.UNSUPPORTED,
            "speculativeDecoding": self.speculative_decoding,
            "draftModelId": self.draft_model,
            "speculativeTokens": self.speculative_decoding,
            "cpuThreads": self.cpu_threads,
            "seed": self.seed,
            "allowMultiGpu": self.gpu_split,
            "shardingMode": self.gpu_split,
            "keepDisplayHeadroom": CapabilitySupport.SUPPORTED,  # Leviathan policy
            "tensorParallelSize": CapabilitySupport.UNSUPPORTED,
        }
        return mapping.get(field_name, CapabilitySupport.UNKNOWN)

    def field_matrix(self) -> tuple[CapabilityField, ...]:
        """Authoritative field-by-field capability matrix for the Models page."""
        S = CapabilitySupport.SUPPORTED
        U = CapabilitySupport.UNSUPPORTED
        sdk = self.sdk_available and self.sdk_reachable
        cli = self.cli_available
        rest = self.native_rest == S

        def _f(
            key: str,
            support: CapabilitySupport,
            scope: CapabilityScope,
            transport: CapabilityTransport,
            reason: str | None = None,
            note: str | None = None,
        ) -> CapabilityField:
            return CapabilityField(key, support, scope, transport, reason, note)

        return (
            _f("contextLength", self.context_length, CapabilityScope.LOAD,
               CapabilityTransport.REST if rest else (CapabilityTransport.SDK if sdk else CapabilityTransport.NONE)),
            _f("evalBatchSize", self.eval_batch, CapabilityScope.LOAD,
               CapabilityTransport.REST if rest else CapabilityTransport.NONE),
            _f("flashAttention", self.flash_attention, CapabilityScope.LOAD,
               CapabilityTransport.REST if rest else CapabilityTransport.NONE),
            _f("offloadKvCacheToGpu", self.kv_gpu_offload, CapabilityScope.LOAD,
               CapabilityTransport.REST if rest else CapabilityTransport.NONE),
            _f("numExperts", self.moe_num_experts, CapabilityScope.LOAD,
               CapabilityTransport.REST if rest else CapabilityTransport.NONE,
               note="MoE models only"),
            _f(
                "gpuOffloadRatio",
                self.gpu_ratio,
                CapabilityScope.LOAD,
                CapabilityTransport.SDK if sdk else (CapabilityTransport.CLI if cli else CapabilityTransport.NONE),
                None if self.gpu_ratio == S else ("SDK_OR_CLI_REQUIRED" if not sdk and not cli else None),
                "Fraction of GPU offload (0–1 / off / max)",
            ),
            _f(
                "seed",
                self.seed,
                CapabilityScope.LOAD,
                CapabilityTransport.SDK if sdk else CapabilityTransport.NONE,
                None if self.seed == S else "SDK_REQUIRED",
                "Official SDK LlmLoadModelConfig.seed",
            ),
            _f(
                "cpuThreads",
                self.cpu_threads,
                CapabilityScope.INFERENCE,
                CapabilityTransport.SDK if sdk else CapabilityTransport.NONE,
                "INFERENCE_ONLY_SETTING" if self.cpu_threads != S else None,
                "Official SDK prediction config — not a load parameter",
            ),
            _f(
                "gpuSplitMode",
                self.gpu_split,
                CapabilityScope.LOAD,
                CapabilityTransport.SDK if sdk else CapabilityTransport.NONE,
                None if self.gpu_split == S else "SDK_REQUIRED",
                "SDK evenly | favorMainGpu strategies",
            ),
            _f(
                "tensorSplit",
                self.custom_gpu_split,
                CapabilityScope.LOAD,
                CapabilityTransport.NONE,
                "SDK_SPLIT_STRATEGY_ONLY",
                "Arbitrary per-GPU % not exposed; use Auto / evenly / favorMainGpu",
            ),
            _f(
                "mainGpuOrdinal",
                self.main_gpu,
                CapabilityScope.LOAD,
                CapabilityTransport.SDK if sdk else CapabilityTransport.NONE,
                None if self.main_gpu == S else "SDK_REQUIRED",
            ),
            _f(
                "excludedDeviceIds",
                self.disabled_gpus,
                CapabilityScope.LOAD,
                CapabilityTransport.SDK if sdk else CapabilityTransport.NONE,
                None if self.disabled_gpus == S else "SDK_REQUIRED",
            ),
            _f(
                "kvCacheDtype",
                self.kv_quantization,
                CapabilityScope.LOAD,
                CapabilityTransport.SDK if sdk else CapabilityTransport.NONE,
                None if self.kv_quantization == S else "SDK_REQUIRED",
            ),
            _f(
                "gpuStrictVramCap",
                self.strict_vram_cap,
                CapabilityScope.LOAD,
                CapabilityTransport.SDK if sdk else CapabilityTransport.NONE,
                None if self.strict_vram_cap == S else "SDK_REQUIRED",
            ),
            _f(
                "speculativeDecoding",
                self.speculative_decoding,
                CapabilityScope.INFERENCE,
                CapabilityTransport.SDK if sdk else CapabilityTransport.NONE,
                "INFERENCE_ONLY_SETTING",
                "draftModel applied at prediction time",
            ),
            _f(
                "draftModelId",
                self.draft_model,
                CapabilityScope.INFERENCE,
                CapabilityTransport.SDK if sdk else CapabilityTransport.NONE,
                "INFERENCE_ONLY_SETTING",
            ),
            _f(
                "speculativeTokens",
                self.speculative_decoding,
                CapabilityScope.INFERENCE,
                CapabilityTransport.SDK if sdk else CapabilityTransport.NONE,
                "INFERENCE_ONLY_SETTING",
            ),
            _f(
                "continuousBatching",
                U,
                CapabilityScope.LOAD,
                CapabilityTransport.NONE,
                "PROVIDER_VERSION_UNSUPPORTED",
                "Not exposed on native REST load; app parallel predictions is separate",
            ),
            _f(
                "prefixCache",
                U,
                CapabilityScope.LOAD,
                CapabilityTransport.NONE,
                "UNSUPPORTED",
                "No official LM Studio prefix-cache control verified",
            ),
            _f(
                "tensorParallelSize",
                U,
                CapabilityScope.LOAD,
                CapabilityTransport.NONE,
                "UNSUPPORTED",
                "LM Studio does not expose tensor-parallel size",
            ),
            _f(
                "keepDisplayHeadroom",
                S,
                CapabilityScope.PLACEMENT_POLICY,
                CapabilityTransport.LEVIATHAN,
                note="Affects ResourceManager / placement / VRAM reserves — not sent to LM Studio",
            ),
            _f(
                "shardingMode",
                self.gpu_split,
                CapabilityScope.LOAD,
                CapabilityTransport.SDK if sdk else CapabilityTransport.NONE,
                None if self.gpu_split == S else "SDK_REQUIRED",
            ),
        )


@dataclass
class CompiledLMStudioLoad:
    """Compiled provider load request for LM Studio."""

    model_key: str
    rest_body: dict[str, Any]
    cli_args: list[str] = field(default_factory=list)
    requested: dict[str, Any] = field(default_factory=dict)
    deferred_unsupported: dict[str, str] = field(default_factory=dict)
    transport: str = "rest"  # rest | cli | hybrid
    warnings: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        rest_public = {
            k: v for k, v in dict(self.rest_body).items() if not str(k).startswith("_")
        }
        return {
            "modelKey": self.model_key,
            "restBody": rest_public,
            "cliArgs": list(self.cli_args),
            "requested": dict(self.requested),
            "deferredUnsupported": dict(self.deferred_unsupported),
            "transport": self.transport,
            "warnings": list(self.warnings),
            "sdkConfig": dict(self.rest_body.get("_sdkConfig") or {})
            if self.transport == "sdk"
            else None,
        }


@dataclass
class LMStudioLoadReceipt:
    requested_model: str
    resolved_model_key: str
    instance_id: str | None
    requested_config: dict[str, Any]
    applied_config: dict[str, Any] | None
    load_time_seconds: float | None
    timestamp: str
    provider_version: str | None = None
    placement_plan_id: str | None = None
    resource_snapshot: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    reconciled: bool = False
    status: str = "loaded"

    def public_dict(self) -> dict[str, Any]:
        return {
            "requestedModel": self.requested_model,
            "resolvedModelKey": self.resolved_model_key,
            "instanceId": self.instance_id,
            "requestedConfig": dict(self.requested_config),
            "appliedConfig": dict(self.applied_config) if self.applied_config else None,
            "loadTimeSeconds": self.load_time_seconds,
            "timestamp": self.timestamp,
            "providerVersion": self.provider_version,
            "placementPlanId": self.placement_plan_id,
            "resourceSnapshot": self.resource_snapshot,
            "warnings": list(self.warnings),
            "reconciled": self.reconciled,
            "status": self.status,
        }


def normalize_lm_studio_host(endpoint: str) -> str:
    """Return scheme://host[:port] without /v1 or /api suffix."""
    text = (endpoint or "").strip().rstrip("/")
    if not text:
        raise ModelControlError(
            code="VALIDATION_ERROR",
            message="LM Studio endpoint cannot be empty",
            http_status=422,
        )
    for suffix in ("/api/v1", "/api/v0", "/v1", "/api"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].rstrip("/")
            break
    return text


def native_api_base(endpoint: str) -> str:
    return f"{normalize_lm_studio_host(endpoint)}/api/v1"


def openai_api_base(endpoint: str) -> str:
    return f"{normalize_lm_studio_host(endpoint)}/v1"


def classify_lm_studio_error(message: str, *, status_code: int | None = None) -> str:
    text = (message or "").lower()
    if status_code == 401 or "unauthorized" in text or "api token" in text or "api key" in text:
        return "LM_STUDIO_AUTH_ERROR"
    if status_code in {502, 503, 504} or "connection" in text or "refused" in text or "offline" in text:
        return "LM_STUDIO_OFFLINE"
    if "not found" in text or "unknown model" in text:
        return "MODEL_NOT_FOUND"
    if "instance" in text and "not found" in text:
        return "INSTANCE_NOT_FOUND"
    if "timeout" in text or "timed out" in text:
        return "LOAD_TIMEOUT"
    if any(
        token in text
        for token in (
            "out of memory",
            "oom",
            "cudamalloc",
            "failed to allocate buffer",
            "allocate buffer for kv cache",
            "cuda error",
        )
    ):
        if "kv cache" in text or "kv-cache" in text:
            return "LOAD_OOM_KV_CACHE"
        if "cudamalloc" in text or "cuda" in text:
            return "LOAD_OOM_CUDA"
        return "LOAD_OOM"
    if "invalid" in text and "config" in text:
        return "INVALID_LOAD_CONFIG"
    if "unsupported" in text:
        return CAPABILITY_NOT_SUPPORTED
    if "unload" in text and ("fail" in text or "error" in text):
        return "UNLOAD_FAILED"
    return "LOAD_FAILED"


def discover_lms_executable() -> str | None:
    return shutil.which("lms")


def run_lms_cli(
    argv: list[str],
    *,
    timeout_seconds: float = 120.0,
    host: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Bounded CLI invocation — argv list, shell=False."""
    exe = discover_lms_executable()
    if not exe:
        raise ModelControlError(
            code=CAPABILITY_NOT_SUPPORTED,
            message="lms CLI not found on PATH",
            http_status=409,
        )
    cmd = [exe, *argv]
    if host:
        cmd.extend(["--host", host])
    try:
        return subprocess.run(
            cmd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=float(timeout_seconds),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ModelControlError(
            code="LOAD_TIMEOUT",
            message=f"lms CLI timed out after {timeout_seconds}s",
            http_status=504,
            details={"argv": argv},
        ) from exc


def parse_lms_estimate_output(stdout: str) -> dict[str, Any]:
    """Parse `lms load --estimate-only` text output."""
    gpu_mem = None
    total_mem = None
    model = None
    note = None
    for line in (stdout or "").splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("model:"):
            model = stripped.split(":", 1)[1].strip()
        m_gpu = re.search(r"Estimated GPU Memory:\s*([\d.]+)\s*([KMGT]?B)", stripped, re.I)
        if m_gpu:
            gpu_mem = _parse_size_to_bytes(m_gpu.group(1), m_gpu.group(2))
        m_tot = re.search(r"Estimated Total Memory:\s*([\d.]+)\s*([KMGT]?B)", stripped, re.I)
        if m_tot:
            total_mem = _parse_size_to_bytes(m_tot.group(1), m_tot.group(2))
        if stripped.lower().startswith("estimate:"):
            note = stripped.split(":", 1)[1].strip()
    return {
        "model": model,
        "estimatedGpuMemoryBytes": gpu_mem,
        "estimatedTotalMemoryBytes": total_mem,
        "note": note,
        "raw": stdout,
        "provenance": "PROVIDER_ESTIMATE",
        "source": "lms load --estimate-only",
    }


def _parse_size_to_bytes(value: str, unit: str) -> int:
    n = float(value)
    u = unit.upper()
    mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}.get(u, 1)
    return int(n * mult)


def capabilities_from_probe(
    *,
    native_rest_ok: bool,
    version: str | None,
    cli_available: bool,
    rest_base: str | None,
    load_probe_ok: bool | None = None,
    sdk_available: bool = False,
    sdk_reachable: bool = False,
    sdk_version: str | None = None,
) -> LMStudioControlCapabilities:
    """Derive field-level capabilities from probe evidence + official docs.

    REST (documented): context_length, eval_batch_size, flash_attention,
    num_experts, offload_kv_cache_to_gpu, echo_load_config.
    CLI (documented): --gpu ratio, --estimate-only, --context-length.
    SDK (documented 1.5.x): seed, gpu.ratio/mainGpu/splitStrategy/disabledGpus,
    KV quant types, gpuStrictVramCap; prediction: cpuThreads, draftModel.
    """
    S = CapabilitySupport.SUPPORTED
    U = CapabilitySupport.UNSUPPORTED
    K = CapabilitySupport.UNKNOWN
    notes: list[str] = []
    sdk_ok = bool(sdk_available and sdk_reachable)

    if not native_rest_ok and not sdk_ok:
        notes.append("Native REST /api/v1 not reachable")
        if sdk_available and not sdk_reachable:
            notes.append("LM Studio SDK installed but not reachable")
        elif not sdk_available:
            notes.append("LM Studio SDK not installed")
        return LMStudioControlCapabilities(
            native_rest=U,
            load=U,
            unload=U,
            loaded_instances=U,
            resource_estimate=S if cli_available else U,
            gpu_ratio=S if (cli_available or sdk_ok) else U,
            gpu_split=S if sdk_ok else U,
            custom_gpu_split=U,
            disabled_gpus=S if sdk_ok else U,
            main_gpu=S if sdk_ok else U,
            strict_vram_cap=S if sdk_ok else U,
            flash_attention=U,
            kv_gpu_offload=U,
            kv_quantization=S if sdk_ok else U,
            eval_batch=U,
            moe_num_experts=U,
            mmap=U,
            mlock=U,
            continuous_batching=U,
            speculative_decoding=S if sdk_ok else U,
            draft_model=S if sdk_ok else U,
            advanced_llama_overrides=U,
            context_length=S if (cli_available or sdk_ok) else U,
            echo_load_config=U,
            seed=S if sdk_ok else U,
            cpu_threads=S if sdk_ok else U,
            provider_version=version,
            cli_available=cli_available,
            sdk_available=sdk_available,
            sdk_reachable=sdk_reachable,
            sdk_version=sdk_version,
            rest_base=rest_base,
            notes=tuple(notes),
        )

    notes.append("Native REST load fields per LM Studio documentation")
    if cli_available:
        notes.append("lms CLI available for --gpu and --estimate-only")
    else:
        notes.append("lms CLI not on PATH — GPU ratio / estimate via CLI unavailable unless SDK")
    if sdk_ok:
        notes.append(
            "LM Studio SDK reachable — seed, GPU strategy, KV quant, inference cpuThreads/draftModel enabled"
        )
    elif sdk_available:
        notes.append("LM Studio SDK installed but not reachable — SDK-only fields disabled")
    else:
        notes.append("LM Studio SDK not installed — seed / multi-GPU strategy / KV quant disabled")
    notes.append(
        "Arbitrary per-GPU % tensor splits are not exposed by LM Studio; use evenly/favorMainGpu"
    )

    load_cap = S if load_probe_ok is not False else K

    return LMStudioControlCapabilities(
        native_rest=S if native_rest_ok else (K if sdk_ok else U),
        load=load_cap if native_rest_ok else (S if sdk_ok else load_cap),
        unload=S if native_rest_ok else (S if sdk_ok else U),
        loaded_instances=S if native_rest_ok else (S if sdk_ok else U),
        resource_estimate=S if cli_available else U,
        gpu_ratio=S if (cli_available or sdk_ok) else U,
        gpu_split=S if sdk_ok else U,
        custom_gpu_split=U,  # no arbitrary % tensor_split
        disabled_gpus=S if sdk_ok else U,
        main_gpu=S if sdk_ok else U,
        strict_vram_cap=S if sdk_ok else U,
        flash_attention=S if native_rest_ok or sdk_ok else U,
        kv_gpu_offload=S if native_rest_ok or sdk_ok else U,
        kv_quantization=S if sdk_ok else U,
        eval_batch=S if native_rest_ok or sdk_ok else U,
        moe_num_experts=S if native_rest_ok or sdk_ok else U,
        mmap=U,
        mlock=U,
        continuous_batching=U,
        speculative_decoding=S if sdk_ok else U,
        draft_model=S if sdk_ok else U,
        advanced_llama_overrides=U,
        context_length=S if native_rest_ok or sdk_ok or cli_available else U,
        echo_load_config=S if native_rest_ok else U,
        seed=S if sdk_ok else U,
        cpu_threads=S if sdk_ok else U,
        provider_version=version,
        cli_available=cli_available,
        sdk_available=sdk_available,
        sdk_reachable=sdk_reachable,
        sdk_version=sdk_version,
        rest_base=rest_base,
        notes=tuple(notes),
    )


def compile_lm_studio_load(
    model_key: str,
    options: LoadOptions | None,
    capabilities: LMStudioControlCapabilities,
    *,
    echo_load_config: bool = True,
    ordinal_by_stable_id: dict[str, int] | None = None,
) -> CompiledLMStudioLoad:
    """Single translation layer: normalized LoadOptions → LM Studio REST/CLI."""
    opts = options or LoadOptions()
    requested: dict[str, Any] = {}
    rest_body: dict[str, Any] = {"model": model_key, "echo_load_config": bool(echo_load_config)}
    deferred: dict[str, str] = {}
    warnings: list[str] = []
    cli_args: list[str] = []
    needs_cli_gpu = False

    def _mark_unsupported(name: str, reason: str) -> None:
        deferred[name] = reason

    # REST-supported
    if opts.context_length is not None:
        requested["contextLength"] = opts.context_length
        if capabilities.context_length == CapabilitySupport.SUPPORTED:
            rest_body["context_length"] = int(opts.context_length)
        else:
            _mark_unsupported("contextLength", "Niet ondersteund door verbonden LM Studio")

    # batch_size maps to eval_batch_size
    if opts.batch_size is not None:
        requested["evalBatchSize"] = opts.batch_size
        if capabilities.eval_batch == CapabilitySupport.SUPPORTED:
            rest_body["eval_batch_size"] = int(opts.batch_size)
        else:
            _mark_unsupported("evalBatchSize", "Niet ondersteund door verbonden LM Studio")

    if opts.flash_attention is not None:
        requested["flashAttention"] = opts.flash_attention
        if capabilities.flash_attention == CapabilitySupport.SUPPORTED:
            rest_body["flash_attention"] = bool(opts.flash_attention)
        else:
            _mark_unsupported("flashAttention", "Niet ondersteund door verbonden LM Studio")

    if opts.offload_kv_cache_to_gpu is not None:
        requested["offloadKvCacheToGpu"] = opts.offload_kv_cache_to_gpu
        if capabilities.kv_gpu_offload == CapabilitySupport.SUPPORTED:
            rest_body["offload_kv_cache_to_gpu"] = bool(opts.offload_kv_cache_to_gpu)
        else:
            _mark_unsupported("offloadKvCacheToGpu", "Niet ondersteund door verbonden LM Studio")

    if opts.num_experts is not None:
        requested["numExperts"] = opts.num_experts
        if capabilities.moe_num_experts == CapabilitySupport.SUPPORTED:
            rest_body["num_experts"] = int(opts.num_experts)
        else:
            _mark_unsupported("numExperts", "Niet ondersteund of niet van toepassing")

    # GPU offload ratio — CLI only (REST does not document this field)
    ratio = opts.gpu_offload_ratio
    if ratio is None and opts.gpu_offload_layers is not None:
        # Interpret layers as percentage when 0–100, else leave unset
        layers = int(opts.gpu_offload_layers)
        if 0 <= layers <= 100:
            ratio = layers / 100.0
            warnings.append("gpuOffloadLayers interpreted as percentage ratio for LM Studio CLI")
    if ratio is not None:
        requested["gpuOffloadRatio"] = ratio
        if capabilities.gpu_ratio == CapabilitySupport.SUPPORTED:
            needs_cli_gpu = True
            if ratio <= 0:
                cli_args.extend(["--gpu", "off"])
            elif ratio >= 1:
                cli_args.extend(["--gpu", "max"])
            else:
                cli_args.extend(["--gpu", f"{float(ratio):.4g}"])
        else:
            _mark_unsupported(
                "gpuOffloadRatio",
                "GPU offload ratio vereist lms CLI (niet in native REST)",
            )

    # Multi-GPU / split — SDK-only today
    if opts.gpu_split_mode is not None or opts.tensor_split is not None or opts.allow_multi_gpu:
        requested["gpuSplitMode"] = opts.gpu_split_mode
        requested["tensorSplit"] = list(opts.tensor_split) if opts.tensor_split else None
        requested["allowMultiGpu"] = opts.allow_multi_gpu
        if capabilities.custom_gpu_split != CapabilitySupport.SUPPORTED:
            _mark_unsupported(
                "gpuSplit",
                "Custom GPU split niet beschikbaar via REST/CLI — Engine Protocol/SDK vereist",
            )

    if opts.main_gpu_ordinal is not None:
        requested["mainGpuOrdinal"] = opts.main_gpu_ordinal
        if capabilities.main_gpu != CapabilitySupport.SUPPORTED:
            _mark_unsupported("mainGpuOrdinal", "Main GPU niet beschikbaar via REST/CLI")

    if opts.excluded_device_ids:
        requested["excludedDeviceIds"] = list(opts.excluded_device_ids)
        if capabilities.disabled_gpus != CapabilitySupport.SUPPORTED:
            _mark_unsupported("excludedDeviceIds", "Disabled GPUs niet beschikbaar via REST/CLI")
        elif ordinal_by_stable_id:
            # Would map stable IDs → ordinals for SDK path
            pass

    if opts.gpu_strict_vram_cap is not None:
        requested["gpuStrictVramCap"] = opts.gpu_strict_vram_cap
        if capabilities.strict_vram_cap != CapabilitySupport.SUPPORTED:
            _mark_unsupported("gpuStrictVramCap", "Niet beschikbaar via REST/CLI")

    for name, value, support in (
        ("kvCacheDtype", opts.kv_cache_dtype, capabilities.kv_quantization),
        ("continuousBatching", opts.continuous_batching, capabilities.continuous_batching),
        ("prefixCache", opts.prefix_cache, CapabilitySupport.UNSUPPORTED),
        ("speculativeDecoding", opts.speculative_decoding, capabilities.speculative_decoding),
        ("draftModelId", opts.draft_model_id, capabilities.draft_model),
        ("speculativeTokens", opts.speculative_tokens, capabilities.speculative_decoding),
        ("cpuThreads", opts.cpu_threads, capabilities.cpu_threads),
        ("seed", opts.seed, capabilities.seed),
        ("tensorParallelSize", opts.tensor_parallel_size, CapabilitySupport.UNSUPPORTED),
    ):
        if value is not None:
            requested[name] = value
            if name == "cpuThreads":
                _mark_unsupported(
                    name,
                    "INFERENCE_ONLY_SETTING: cpuThreads is prediction config, not load",
                )
            elif name in {"speculativeDecoding", "draftModelId", "speculativeTokens"}:
                _mark_unsupported(
                    name,
                    "INFERENCE_ONLY_SETTING: draftModel applied at prediction time",
                )
            elif name == "seed" and support == CapabilitySupport.SUPPORTED:
                # Seed requires SDK transport — mark for SDK path below.
                pass
            elif support != CapabilitySupport.SUPPORTED:
                _mark_unsupported(
                    name,
                    f"Niet ondersteund door LM Studio {capabilities.provider_version or 'via REST/CLI'}",
                )

    if opts.keep_display_headroom is not None:
        requested["keepDisplayHeadroom"] = opts.keep_display_headroom
        warnings.append("keepDisplayHeadroom is Leviathan placement policy (not sent to LM Studio)")

    needs_sdk = False
    if opts.seed is not None and capabilities.seed == CapabilitySupport.SUPPORTED:
        needs_sdk = True
    if opts.kv_cache_dtype and capabilities.kv_quantization == CapabilitySupport.SUPPORTED:
        needs_sdk = True
    if opts.main_gpu_ordinal is not None and capabilities.main_gpu == CapabilitySupport.SUPPORTED:
        needs_sdk = True
    if opts.gpu_split_mode and capabilities.gpu_split == CapabilitySupport.SUPPORTED:
        needs_sdk = True
    if opts.gpu_strict_vram_cap is not None and capabilities.strict_vram_cap == CapabilitySupport.SUPPORTED:
        needs_sdk = True
    if (
        ratio is not None
        and capabilities.gpu_ratio == CapabilitySupport.SUPPORTED
        and capabilities.sdk_available
        and capabilities.sdk_reachable
        and not capabilities.cli_available
    ):
        needs_sdk = True

    transport = "rest"
    if needs_sdk and capabilities.sdk_available and capabilities.sdk_reachable:
        transport = "sdk"
        # Build SDK config via dedicated compiler; REST body retained as fallback metadata.
        from Data.modules.models.lm_studio_sdk import compile_sdk_load_config

        sdk_plan = compile_sdk_load_config(model_key, opts)
        # Merge requested + deferred from SDK plan (authoritative for SDK fields)
        requested.update(sdk_plan.requested)
        deferred.update(sdk_plan.deferred_unsupported)
        warnings.extend(sdk_plan.warnings)
        # Stash SDK config on rest_body under a private key for adapter (not sent to REST)
        rest_body["_sdkConfig"] = sdk_plan.config
        warnings.append("Load will use LM Studio SDK transport for supported fields")
    elif needs_cli_gpu and capabilities.cli_available:
        # Hybrid: prefer CLI when GPU ratio must be applied (CLI owns load in that case)
        transport = "cli"
        if opts.context_length is not None and "--context-length" not in cli_args:
            cli_args.extend(["--context-length", str(int(opts.context_length))])
        warnings.append(
            "GPU offload ratio applied via lms CLI; REST-only fields also sent when using REST fallback"
        )
    elif needs_cli_gpu and not capabilities.cli_available:
        warnings.append("GPU ratio requested but lms CLI unavailable — REST load without GPU ratio")

    # Strip private SDK stash from public REST body copy for deferred inspection —
    # adapter reads compiled.rest_body.get("_sdkConfig").
    return CompiledLMStudioLoad(
        model_key=model_key,
        rest_body=rest_body,
        cli_args=cli_args,
        requested=requested,
        deferred_unsupported=deferred,
        transport=transport,
        warnings=warnings,
    )


def config_fingerprint(
    *,
    model_id: str,
    quantization: str | None,
    provider_version: str | None,
    hardware_fingerprint: str | None,
    options: LoadOptions | None,
) -> str:
    import hashlib

    opts = options or LoadOptions()
    payload = {
        "modelId": model_id,
        "quantization": quantization,
        "providerVersion": provider_version,
        "hardware": hardware_fingerprint,
        "contextLength": opts.context_length,
        "batchSize": opts.batch_size,
        "flashAttention": opts.flash_attention,
        "offloadKvCacheToGpu": opts.offload_kv_cache_to_gpu,
        "gpuOffloadRatio": opts.gpu_offload_ratio,
        "tensorSplit": list(opts.tensor_split) if opts.tensor_split else None,
        "kvCacheDtype": opts.kv_cache_dtype,
        "numExperts": opts.num_experts,
        "gpuSplitMode": opts.gpu_split_mode,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
