"""Optional official LM Studio Python SDK bridge.

Extends the existing LM Studio provider boundary — does not create a second
provider architecture. Import is defensive: absence of the SDK yields a truthful
capability downgrade rather than crashing the Model Control Plane.

SDK docs (1.5.x):
  - Load: LlmLoadModelConfig (seed, gpu, flashAttention, KV quant, …)
  - Prediction: LlmPredictionConfig (cpuThreads, draftModel, …)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from Data.modules.models.contracts import LoadOptions
from Data.modules.models.errors import ModelControlError

logger = logging.getLogger(__name__)


def probe_sdk_import() -> tuple[bool, str | None]:
    """Return (available, version_or_error). Never raises."""
    try:
        import lmstudio as lms  # noqa: F401

        version = getattr(lms, "__version__", None) or "installed"
        return True, str(version)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def api_host_from_endpoint(endpoint: str) -> str:
    """Map Leviathan endpoint (http://127.0.0.1:1234/v1) → SDK api_host host:port."""
    from Data.modules.models.lm_studio_control import normalize_lm_studio_host

    host = normalize_lm_studio_host(endpoint)
    parsed = urlparse(host if "://" in host else f"http://{host}")
    hostname = parsed.hostname or "127.0.0.1"
    port = parsed.port or 1234
    return f"{hostname}:{port}"


@dataclass
class SdkLoadPlan:
    """Compiled SDK load request (never claims applied until provider confirms)."""

    model_key: str
    config: dict[str, Any] = field(default_factory=dict)
    requested: dict[str, Any] = field(default_factory=dict)
    deferred_unsupported: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    api_host: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "modelKey": self.model_key,
            "config": dict(self.config),
            "requested": dict(self.requested),
            "deferredUnsupported": dict(self.deferred_unsupported),
            "warnings": list(self.warnings),
            "apiHost": self.api_host,
            "transport": "sdk",
        }


def compile_sdk_load_config(
    model_key: str,
    options: LoadOptions | None,
    *,
    api_host: str | None = None,
) -> SdkLoadPlan:
    """Compile LoadOptions into an official SDK LlmLoadModelConfig dict."""
    opts = options or LoadOptions()
    config: dict[str, Any] = {}
    requested: dict[str, Any] = {}
    deferred: dict[str, str] = {}
    warnings: list[str] = []

    if opts.context_length is not None:
        requested["contextLength"] = opts.context_length
        config["contextLength"] = int(opts.context_length)
    if opts.batch_size is not None:
        requested["evalBatchSize"] = opts.batch_size
        config["evalBatchSize"] = int(opts.batch_size)
    if opts.flash_attention is not None:
        requested["flashAttention"] = opts.flash_attention
        config["flashAttention"] = bool(opts.flash_attention)
    if opts.offload_kv_cache_to_gpu is not None:
        requested["offloadKvCacheToGpu"] = opts.offload_kv_cache_to_gpu
        config["offloadKVCacheToGpu"] = bool(opts.offload_kv_cache_to_gpu)
    if opts.num_experts is not None:
        requested["numExperts"] = opts.num_experts
        config["numExperts"] = int(opts.num_experts)
    if opts.seed is not None:
        requested["seed"] = opts.seed
        config["seed"] = int(opts.seed)
    if opts.gpu_strict_vram_cap is not None:
        requested["gpuStrictVramCap"] = opts.gpu_strict_vram_cap
        config["gpuStrictVramCap"] = bool(opts.gpu_strict_vram_cap)

    # KV cache dtype — map UI combined setting to K+V SDK fields when not auto.
    if opts.kv_cache_dtype and str(opts.kv_cache_dtype).lower() not in {"auto", "none", ""}:
        dtype = str(opts.kv_cache_dtype).lower()
        requested["kvCacheDtype"] = dtype
        allowed = {"f32", "f16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"}
        if dtype in allowed:
            config["llamaKCacheQuantizationType"] = dtype
            config["llamaVCacheQuantizationType"] = dtype
        elif dtype in {"fp16", "float16"}:
            config["useFp16ForKVCache"] = True
            requested["useFp16ForKVCache"] = True
        else:
            deferred["kvCacheDtype"] = f"Unsupported KV dtype for SDK: {dtype}"

    gpu: dict[str, Any] = {}
    ratio = opts.gpu_offload_ratio
    if ratio is not None:
        requested["gpuOffloadRatio"] = ratio
        if ratio <= 0:
            gpu["ratio"] = "off"
        elif ratio >= 1:
            gpu["ratio"] = "max"
        else:
            gpu["ratio"] = float(ratio)

    # SDK multi-GPU: evenly | favorMainGpu — NOT arbitrary per-device % tensor_split.
    if opts.tensor_split is not None:
        requested["tensorSplit"] = list(opts.tensor_split)
        deferred["tensorSplit"] = (
            "SDK_SPLIT_STRATEGY_ONLY: LM Studio SDK exposes evenly/favorMainGpu, "
            "not arbitrary per-GPU percentage tensor splits"
        )
        warnings.append(deferred["tensorSplit"])

    split_mode = (opts.gpu_split_mode or "").strip().lower() if opts.gpu_split_mode else None
    if split_mode:
        requested["gpuSplitMode"] = split_mode
        if split_mode in {"evenly", "auto"}:
            gpu["splitStrategy"] = "evenly"
        elif split_mode in {"favor_main", "favormaingpu", "priority", "manual"}:
            # "manual" without tensor_split → favor main GPU strategy
            gpu["splitStrategy"] = "favorMainGpu"
            if split_mode == "manual":
                warnings.append(
                    "Manual GPU split mapped to SDK favorMainGpu (no per-device %)"
                )
        elif split_mode == "single":
            # Single GPU: leave split unset; mainGpu may pin
            pass
        else:
            deferred["gpuSplitMode"] = f"Unknown GPU split mode: {split_mode}"

    if opts.main_gpu_ordinal is not None:
        requested["mainGpuOrdinal"] = opts.main_gpu_ordinal
        gpu["mainGpu"] = int(opts.main_gpu_ordinal)

    if opts.excluded_device_ids:
        requested["excludedDeviceIds"] = list(opts.excluded_device_ids)
        # Caller must map stable IDs → ordinals before SDK; if already ordinals as ints in ids…
        ordinals: list[int] = []
        for raw in opts.excluded_device_ids:
            try:
                ordinals.append(int(str(raw).rsplit(":", 1)[-1]))
            except ValueError:
                deferred["excludedDeviceIds"] = (
                    "Excluded device IDs must be mapped to provider ordinals for SDK"
                )
                ordinals = []
                break
        if ordinals:
            gpu["disabledGpus"] = ordinals

    if gpu:
        config["gpu"] = gpu

    # Inference-scoped fields must NEVER enter load config.
    if opts.cpu_threads is not None:
        requested["cpuThreads"] = opts.cpu_threads
        deferred["cpuThreads"] = "INFERENCE_ONLY_SETTING: cpuThreads belongs on prediction config"
    if opts.speculative_decoding is not None or opts.draft_model_id is not None:
        if opts.speculative_decoding is not None:
            requested["speculativeDecoding"] = opts.speculative_decoding
        if opts.draft_model_id is not None:
            requested["draftModelId"] = opts.draft_model_id
        deferred["speculativeDecoding"] = (
            "INFERENCE_ONLY_SETTING: draftModel is applied at prediction time, not load"
        )
    if opts.prefix_cache is not None:
        requested["prefixCache"] = opts.prefix_cache
        deferred["prefixCache"] = "UNSUPPORTED: no official LM Studio load/prediction prefix-cache control"
    if opts.continuous_batching is not None:
        requested["continuousBatching"] = opts.continuous_batching
        deferred["continuousBatching"] = (
            "UNSUPPORTED via public SDK load config (app maxParallelPredictions is separate)"
        )
    if opts.tensor_parallel_size is not None and opts.tensor_parallel_size not in (0, 1):
        requested["tensorParallelSize"] = opts.tensor_parallel_size
        deferred["tensorParallelSize"] = "UNSUPPORTED: LM Studio has no tensor-parallel size control"
    if opts.keep_display_headroom is not None:
        requested["keepDisplayHeadroom"] = opts.keep_display_headroom
        # Leviathan placement policy — not an LM Studio field
        warnings.append("keepDisplayHeadroom is Leviathan placement policy (not sent to SDK)")

    return SdkLoadPlan(
        model_key=model_key,
        config=config,
        requested=requested,
        deferred_unsupported=deferred,
        warnings=warnings,
        api_host=api_host,
    )


def compile_sdk_prediction_config(options: LoadOptions | None) -> dict[str, Any]:
    """Compile inference-scoped options for official SDK prediction config."""
    opts = options or LoadOptions()
    pred: dict[str, Any] = {}
    if opts.cpu_threads is not None:
        pred["cpuThreads"] = int(opts.cpu_threads)
    if opts.speculative_decoding and opts.draft_model_id:
        pred["draftModel"] = str(opts.draft_model_id)
    if opts.speculative_tokens is not None and opts.speculative_decoding:
        pred["speculativeDecodingNumDraftTokensExact"] = int(opts.speculative_tokens)
    return pred


def sdk_load_model(
    *,
    endpoint: str,
    model_key: str,
    config: dict[str, Any],
    timeout_seconds: float = 600.0,
    identifier: str | None = None,
) -> dict[str, Any]:
    """Execute an official SDK load with a real wall-clock timeout bound.

    Native SDK calls are blocking. We run them in a worker thread and enforce
    ``timeout_seconds`` via ``concurrent.futures``. A late thread return after
    timeout must NOT be treated as success by the caller — this function raises
    REQUEST_TIMEOUT and does not return a loaded receipt.

    Hard cancellation of the native SDK call is not guaranteed (Python threads
    cannot kill native work). Callers must reconcile/list-loaded after timeout.
    """
    import concurrent.futures

    available, detail = probe_sdk_import()
    if not available:
        raise ModelControlError(
            code="CAPABILITY_NOT_SUPPORTED",
            message=f"LM Studio SDK unavailable: {detail}",
            http_status=409,
            details={"reason": "SDK_REQUIRED", "detail": detail},
        )
    import lmstudio as lms
    from lmstudio import LlmLoadModelConfig

    api_host = api_host_from_endpoint(endpoint)
    try:
        load_cfg = LlmLoadModelConfig.from_dict(config) if config else None
    except Exception as exc:  # noqa: BLE001
        raise ModelControlError(
            code="INVALID_LOAD_CONFIG",
            message=f"Invalid LM Studio SDK load config: {exc}",
            http_status=422,
            details={"config": {k: v for k, v in (config or {}).items() if "key" not in str(k).lower()}},
        ) from exc

    def _do_load() -> dict[str, Any]:
        with lms.Client(api_host) as client:
            handle = client.llm.load_new_instance(
                model_key,
                identifier,
                config=load_cfg,
            )
            info = None
            try:
                info = handle.get_model_info() if hasattr(handle, "get_model_info") else None
            except Exception:  # noqa: BLE001
                info = None
            instance_id = None
            applied = None
            if info is not None:
                if hasattr(info, "to_dict"):
                    info_dict = info.to_dict()
                elif isinstance(info, dict):
                    info_dict = info
                else:
                    info_dict = {"repr": repr(info)}
                instance_id = (
                    info_dict.get("identifier")
                    or info_dict.get("instanceId")
                    or info_dict.get("id")
                )
                applied = info_dict.get("loadConfig") or info_dict.get("load_config")
            else:
                instance_id = getattr(handle, "identifier", None) or getattr(
                    handle, "id", None
                )
            return {
                "status": "loaded",
                "transport": "sdk",
                "apiHost": api_host,
                "modelKey": model_key,
                "instanceId": str(instance_id) if instance_id else None,
                "loadConfig": applied,
                "timeoutSeconds": timeout_seconds,
                "timeoutEnforced": True,
            }

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_do_load)
    try:
        try:
            return future.result(timeout=float(timeout_seconds))
        except concurrent.futures.TimeoutError as exc:
            # Do not wait for late completion; abandon the future.
            future.cancel()
            raise ModelControlError(
                code="REQUEST_TIMEOUT",
                message=(
                    f"LM Studio SDK load timed out after {timeout_seconds}s "
                    "(native call may still complete in background — reconcile required)"
                ),
                http_status=504,
                details={
                    "transport": "sdk",
                    "apiHost": api_host,
                    "modelKey": model_key,
                    "timeoutSeconds": timeout_seconds,
                    "timeoutEnforced": True,
                    "softCancelOnly": True,
                    "reconcileRequired": True,
                },
            ) from exc
        except ModelControlError:
            raise
        except Exception as exc:  # noqa: BLE001
            from Data.modules.models.lm_studio_control import classify_lm_studio_error

            code = classify_lm_studio_error(str(exc))
            raise ModelControlError(
                code=code,
                message=f"LM Studio SDK load failed: {exc}",
                http_status=502,
                details={"transport": "sdk", "apiHost": api_host, "modelKey": model_key},
            ) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def sdk_probe_reachable(endpoint: str, *, timeout_seconds: float = 5.0) -> bool:
    """Best-effort SDK reachability probe with real timeout. Never raises."""
    import concurrent.futures

    available, _ = probe_sdk_import()
    if not available:
        return False

    def _probe() -> bool:
        import lmstudio as lms

        api_host = api_host_from_endpoint(endpoint)
        with lms.Client(api_host) as client:
            client.llm.list_loaded()
        return True

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_probe)
    try:
        return bool(future.result(timeout=float(timeout_seconds)))
    except Exception as exc:  # noqa: BLE001
        logger.debug("LM Studio SDK probe failed: %s", exc)
        return False
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
