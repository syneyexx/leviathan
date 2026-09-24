"""Typed backend launch strategy — verified options only, no shell=True.

Produces argv + environment from DeploymentPlan / LoadOptions.
Physical ordinals may remap under CUDA_VISIBLE_DEVICES; both identities are recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from Data.modules.models.contracts import (
    DeploymentPlan,
    LoadOptions,
    MultiGpuCapability,
    ShardingMode,
)
from Data.modules.models.errors import (
    MULTI_GPU_UNSUPPORTED,
    UNSUPPORTED_LOAD_OPTION,
    ModelControlError,
)
from Data.modules.model_runtime.llama_cpp_command import build_llama_cpp_command


@dataclass(frozen=True)
class LaunchSpec:
    argv: tuple[str, ...]
    env: dict[str, str] = field(default_factory=dict)
    endpoint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "env": dict(self.env),
            "endpoint": self.endpoint,
            "metadata": dict(self.metadata),
            "truth": {
                "noShell": True,
                "verifiedOptionsOnly": True,
            },
        }


# Capability keys that may be applied when SUPPORTED / advertised.
_LLAMA_CPP_LOAD_OPTIONS = (
    "contextLength",
    "gpuOffloadLayers",
    "cpuThreads",
    "batchSize",
    "flashAttention",
    "tensorSplit",
    "mainGpuOrdinal",
    "pinnedDeviceIds",
    "preferredDeviceIds",
    "allowMultiGpu",
    "shardingMode",
)

_VLLM_LOAD_OPTIONS = (
    "contextLength",
    "gpuMemoryLimitBytes",
    "tensorParallelSize",
    "pinnedDeviceIds",
    "preferredDeviceIds",
    "allowMultiGpu",
    "shardingMode",
)


def build_cuda_visible_devices(ordinals: Sequence[int]) -> str:
    """Build CUDA_VISIBLE_DEVICES from physical ordinals. Validates non-negative ints."""
    cleaned: list[str] = []
    for ord_ in ordinals:
        if not isinstance(ord_, int) or ord_ < 0:
            raise ValueError(f"invalid GPU ordinal: {ord_!r}")
        cleaned.append(str(ord_))
    return ",".join(cleaned)


def physical_to_visible_mapping(ordinals: Sequence[int]) -> dict[str, int]:
    """Map physical ordinal → process-visible ordinal after CUDA_VISIBLE_DEVICES."""
    return {str(physical): visible for visible, physical in enumerate(ordinals)}


class BackendLaunchStrategy:
    """Produce safe argv/env for managed backends from a DeploymentPlan."""

    def __init__(
        self,
        *,
        backend_kind: str,
        multi_gpu_capability: MultiGpuCapability = MultiGpuCapability.UNKNOWN,
        supported_load_options: Sequence[str] | None = None,
        base_command: Sequence[str] | None = None,
        executable: str | Path | None = None,
        model_path: str | Path | None = None,
        host: str = "127.0.0.1",
        port: int | None = None,
    ) -> None:
        self.backend_kind = backend_kind
        self.multi_gpu_capability = multi_gpu_capability
        self.base_command = list(base_command or [])
        self.executable = executable
        self.model_path = model_path
        self.host = host
        self.port = port
        if supported_load_options is not None:
            self.supported_load_options = tuple(supported_load_options)
        elif backend_kind in {"llama_cpp", "llama.cpp"}:
            self.supported_load_options = _LLAMA_CPP_LOAD_OPTIONS
        elif backend_kind in {"vllm_class", "vllm"}:
            self.supported_load_options = _VLLM_LOAD_OPTIONS
        else:
            self.supported_load_options = ()

    def build(
        self,
        *,
        plan: DeploymentPlan | None = None,
        options: LoadOptions | None = None,
        endpoint: str | None = None,
    ) -> LaunchSpec:
        opts = options or (plan.load_options if plan else None)
        devices = list(plan.devices) if plan else []
        ordinals = [d.ordinal for d in devices if d.ordinal is not None]
        env: dict[str, str] = {}
        meta: dict[str, Any] = {
            "backendKind": self.backend_kind,
            "stableDeviceIds": [d.stable_device_id for d in devices],
            "physicalOrdinals": ordinals,
            "shardingMode": plan.sharding_mode.value if plan else ShardingMode.NONE.value,
        }

        if ordinals:
            cvd = build_cuda_visible_devices(ordinals)
            env["CUDA_VISIBLE_DEVICES"] = cvd
            meta["cudaVisibleDevices"] = cvd
            meta["physicalToVisible"] = physical_to_visible_mapping(ordinals)

        if self.backend_kind in {"llama_cpp", "llama.cpp"}:
            return self._build_llama_cpp(plan=plan, options=opts, env=env, meta=meta, endpoint=endpoint)
        if self.backend_kind in {"vllm_class", "vllm"}:
            return self._build_vllm(plan=plan, options=opts, env=env, meta=meta, endpoint=endpoint)
        # External / unknown managed: pass through base command with device env only.
        argv = tuple(self.base_command)
        if not argv:
            raise ModelControlError(
                code=UNSUPPORTED_LOAD_OPTION,
                message=f"no launch command configured for backend {self.backend_kind}",
                http_status=409,
            )
        return LaunchSpec(argv=argv, env=env, endpoint=endpoint, metadata=meta)

    def _reject_unverified_multi_gpu(self, plan: DeploymentPlan | None, options: LoadOptions | None) -> None:
        wants = False
        if plan and plan.sharding_mode != ShardingMode.NONE:
            wants = True
        if options and options.allow_multi_gpu is True:
            wants = True
        if options and options.tensor_split:
            wants = True
        if options and options.tensor_parallel_size and options.tensor_parallel_size > 1:
            wants = True
        if not wants:
            return
        if self.multi_gpu_capability != MultiGpuCapability.SUPPORTED:
            raise ModelControlError(
                code=MULTI_GPU_UNSUPPORTED,
                message="Multi-GPU requested but runtime multi-GPU capability is not verified SUPPORTED",
                http_status=409,
                details={
                    "multiGpuCapability": self.multi_gpu_capability.value,
                    "truth": {"noUnverifiedFlags": True},
                },
            )

    def _build_llama_cpp(
        self,
        *,
        plan: DeploymentPlan | None,
        options: LoadOptions | None,
        env: dict[str, str],
        meta: dict[str, Any],
        endpoint: str | None,
    ) -> LaunchSpec:
        self._reject_unverified_multi_gpu(plan, options)
        if self.executable and self.model_path and self.port is not None:
            cmd = build_llama_cpp_command(
                executable=self.executable,
                model_path=self.model_path,
                host=self.host,
                port=int(self.port),
                options=options,
            )
        elif self.base_command:
            cmd = list(self.base_command)
            self._apply_llama_flags(cmd, options)
        else:
            raise ModelControlError(
                code=UNSUPPORTED_LOAD_OPTION,
                message="llama.cpp launch requires executable+model_path+port or base_command",
                http_status=409,
            )

        # Device-scoped flags that are verified for managed llama.cpp path.
        if options and options.tensor_split and "tensorSplit" in self.supported_load_options:
            if self.multi_gpu_capability == MultiGpuCapability.SUPPORTED:
                split = ",".join(str(x) for x in options.tensor_split)
                self._upsert_flag(cmd, "--tensor-split", split)
                meta["tensorSplit"] = list(options.tensor_split)
            else:
                raise ModelControlError(
                    code=MULTI_GPU_UNSUPPORTED,
                    message="tensor-split requested but multi-GPU capability is not SUPPORTED",
                    http_status=409,
                )
        if options and options.main_gpu_ordinal is not None and "mainGpuOrdinal" in self.supported_load_options:
            # After CUDA_VISIBLE_DEVICES remap, main GPU is process-visible 0 for single device.
            main = int(options.main_gpu_ordinal)
            self._upsert_flag(cmd, "--main-gpu", str(main))
            meta["mainGpu"] = main

        return LaunchSpec(argv=tuple(cmd), env=env, endpoint=endpoint, metadata=meta)

    def _apply_llama_flags(self, cmd: list[str], options: LoadOptions | None) -> None:
        if options is None:
            return
        # Only append if not already present in base command.
        if options.context_length is not None and "-c" not in cmd:
            cmd.extend(["-c", str(int(options.context_length))])
        if options.gpu_offload_layers is not None and "-ngl" not in cmd:
            cmd.extend(["-ngl", str(int(options.gpu_offload_layers))])
        if options.cpu_threads is not None and "-t" not in cmd:
            cmd.extend(["-t", str(int(options.cpu_threads))])
        if options.batch_size is not None and "-b" not in cmd:
            cmd.extend(["-b", str(int(options.batch_size))])
        if options.flash_attention is True and "-fa" not in cmd:
            cmd.append("-fa")

    def _build_vllm(
        self,
        *,
        plan: DeploymentPlan | None,
        options: LoadOptions | None,
        env: dict[str, str],
        meta: dict[str, Any],
        endpoint: str | None,
    ) -> LaunchSpec:
        self._reject_unverified_multi_gpu(plan, options)
        cmd = list(self.base_command)
        if not cmd:
            raise ModelControlError(
                code=UNSUPPORTED_LOAD_OPTION,
                message="vLLM-class launch requires a configured base_command",
                http_status=409,
            )
        if options and options.tensor_parallel_size and options.tensor_parallel_size > 1:
            if self.multi_gpu_capability != MultiGpuCapability.SUPPORTED:
                raise ModelControlError(
                    code=MULTI_GPU_UNSUPPORTED,
                    message="tensor-parallel requested but multi-GPU capability is not SUPPORTED",
                    http_status=409,
                )
            self._upsert_flag(cmd, "--tensor-parallel-size", str(int(options.tensor_parallel_size)))
            meta["tensorParallelSize"] = int(options.tensor_parallel_size)
        if options and options.context_length is not None:
            self._upsert_flag(cmd, "--max-model-len", str(int(options.context_length)))
        if options and options.gpu_memory_limit_bytes is not None:
            # vLLM uses gpu-memory-utilization fraction — only if we know total; else skip.
            meta["gpuMemoryLimitBytesRequested"] = int(options.gpu_memory_limit_bytes)
            meta["gpuMemoryLimitNote"] = "bytes limit recorded; fraction flag requires device total"
        return LaunchSpec(argv=tuple(cmd), env=env, endpoint=endpoint, metadata=meta)

    @staticmethod
    def _upsert_flag(cmd: list[str], flag: str, value: str | None = None) -> None:
        if flag in cmd:
            idx = cmd.index(flag)
            if value is not None and idx + 1 < len(cmd) and not cmd[idx + 1].startswith("-"):
                cmd[idx + 1] = value
            return
        if value is None:
            cmd.append(flag)
        else:
            cmd.extend([flag, value])
