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


# Official native REST load body fields (LM Studio 0.4.x docs).
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
)


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
    provider_version: str | None = None
    cli_available: bool = False
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
            }.items()
        }
        return {
            **fields,
            "providerVersion": self.provider_version,
            "cliAvailable": self.cli_available,
            "restBase": self.rest_base,
            "notes": list(self.notes),
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
            "cpuThreads": CapabilitySupport.UNSUPPORTED,
            "seed": CapabilitySupport.UNSUPPORTED,
            "allowMultiGpu": self.gpu_split,
            "shardingMode": self.gpu_split,
        }
        return mapping.get(field_name, CapabilitySupport.UNKNOWN)


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
        return {
            "modelKey": self.model_key,
            "restBody": dict(self.rest_body),
            "cliArgs": list(self.cli_args),
            "requested": dict(self.requested),
            "deferredUnsupported": dict(self.deferred_unsupported),
            "transport": self.transport,
            "warnings": list(self.warnings),
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
) -> LMStudioControlCapabilities:
    """Derive field-level capabilities from probe evidence + official docs.

    REST (documented): context_length, eval_batch_size, flash_attention,
    num_experts, offload_kv_cache_to_gpu, echo_load_config.
    CLI (documented): --gpu ratio, --estimate-only, --context-length.
    SDK-only (not exposed via REST/CLI): custom GPU split ratios, strict VRAM
    cap, KV quantization types, continuous batching, speculative decoding.
    Those remain UNSUPPORTED unless a typed Engine Protocol bridge exists.
    """
    S = CapabilitySupport.SUPPORTED
    U = CapabilitySupport.UNSUPPORTED
    K = CapabilitySupport.UNKNOWN
    notes: list[str] = []

    if not native_rest_ok:
        notes.append("Native REST /api/v1 not reachable")
        return LMStudioControlCapabilities(
            native_rest=U,
            load=U,
            unload=U,
            loaded_instances=U,
            resource_estimate=S if cli_available else U,
            gpu_ratio=S if cli_available else U,
            gpu_split=U,
            custom_gpu_split=U,
            disabled_gpus=U,
            main_gpu=U,
            strict_vram_cap=U,
            flash_attention=U,
            kv_gpu_offload=U,
            kv_quantization=U,
            eval_batch=U,
            moe_num_experts=U,
            mmap=U,
            mlock=U,
            continuous_batching=U,
            speculative_decoding=U,
            draft_model=U,
            advanced_llama_overrides=U,
            context_length=U,
            echo_load_config=U,
            provider_version=version,
            cli_available=cli_available,
            rest_base=rest_base,
            notes=tuple(notes),
        )

    notes.append("Native REST load fields per LM Studio 0.4.x documentation")
    if cli_available:
        notes.append("lms CLI available for --gpu and --estimate-only")
    else:
        notes.append("lms CLI not on PATH — GPU ratio / estimate via CLI unavailable")
    notes.append(
        "Custom GPU split / KV quantization / speculative decoding require "
        "Engine Protocol / SDK — not exposed on REST; controls disabled"
    )

    load_cap = S if load_probe_ok is not False else K

    return LMStudioControlCapabilities(
        native_rest=S,
        load=load_cap,
        unload=S,
        loaded_instances=S,
        resource_estimate=S if cli_available else U,
        gpu_ratio=S if cli_available else U,
        gpu_split=U,
        custom_gpu_split=U,
        disabled_gpus=U,
        main_gpu=U,
        strict_vram_cap=U,
        flash_attention=S,
        kv_gpu_offload=S,
        kv_quantization=U,
        eval_batch=S,
        moe_num_experts=S,
        mmap=U,
        mlock=U,
        continuous_batching=U,
        speculative_decoding=U,
        draft_model=U,
        advanced_llama_overrides=U,
        context_length=S,
        echo_load_config=S,
        provider_version=version,
        cli_available=cli_available,
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
        ("cpuThreads", opts.cpu_threads, CapabilitySupport.UNSUPPORTED),
        ("seed", opts.seed, CapabilitySupport.UNSUPPORTED),
    ):
        if value is not None:
            requested[name] = value
            if support != CapabilitySupport.SUPPORTED:
                _mark_unsupported(
                    name,
                    f"Niet ondersteund door LM Studio {capabilities.provider_version or 'via REST/CLI'}",
                )

    transport = "rest"
    if needs_cli_gpu and capabilities.cli_available:
        # Hybrid: prefer CLI when GPU ratio must be applied (CLI owns load in that case)
        transport = "cli"
        if opts.context_length is not None and "--context-length" not in cli_args:
            cli_args.extend(["--context-length", str(int(opts.context_length))])
        warnings.append(
            "GPU offload ratio applied via lms CLI; REST-only fields also sent when using REST fallback"
        )
    elif needs_cli_gpu and not capabilities.cli_available:
        warnings.append("GPU ratio requested but lms CLI unavailable — REST load without GPU ratio")

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
