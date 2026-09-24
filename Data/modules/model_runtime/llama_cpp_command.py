"""llama.cpp managed server argument builder — no shell concatenation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from Data.modules.models.contracts import LoadOptions


# Flags commonly supported by llama-server / llama.cpp OpenAI-compatible server.
_SUPPORTED_OPTION_KEYS = frozenset(
    {
        "contextLength",
        "gpuOffloadLayers",
        "cpuThreads",
        "batchSize",
        "flashAttention",
        "tensorSplit",
        "mainGpuOrdinal",
    }
)


def build_llama_cpp_command(
    *,
    executable: str | Path,
    model_path: str | Path,
    host: str = "127.0.0.1",
    port: int,
    options: LoadOptions | None = None,
    extra_args: Sequence[str] | None = None,
) -> list[str]:
    """Build a subprocess argv for a managed llama.cpp OpenAI-compatible server.

    Never uses shell=True. Rejects empty executable/model paths.
    tensor-split / main-gpu are only emitted when present on LoadOptions
    (caller must gate on verified multi-GPU capability).
    """
    exe = str(executable).strip()
    model = str(model_path).strip()
    if not exe:
        raise ValueError("llama.cpp executable path is required")
    if not model:
        raise ValueError("GGUF model path is required")
    if port <= 0 or port > 65535:
        raise ValueError(f"invalid port: {port}")

    cmd: list[str] = [
        exe,
        "-m",
        model,
        "--host",
        host,
        "--port",
        str(int(port)),
    ]
    if options is not None:
        if options.context_length is not None:
            cmd.extend(["-c", str(int(options.context_length))])
        if options.gpu_offload_layers is not None:
            cmd.extend(["-ngl", str(int(options.gpu_offload_layers))])
        if options.cpu_threads is not None:
            cmd.extend(["-t", str(int(options.cpu_threads))])
        if options.batch_size is not None:
            cmd.extend(["-b", str(int(options.batch_size))])
        if options.flash_attention is True:
            cmd.append("-fa")
        if options.tensor_split:
            cmd.extend(["--tensor-split", ",".join(str(x) for x in options.tensor_split)])
        if options.main_gpu_ordinal is not None:
            cmd.extend(["--main-gpu", str(int(options.main_gpu_ordinal))])
        if options.gpu_memory_limit_bytes is not None:
            # Not a universal llama.cpp flag — leave for adapters that advertise it.
            pass
    if extra_args:
        for arg in extra_args:
            if not isinstance(arg, str) or not arg:
                raise ValueError("extra_args must be non-empty strings")
            cmd.append(arg)
    return cmd


def filter_supported_load_options(
    options: LoadOptions | None,
    allowed: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return only options supported by llama.cpp managed path."""
    if options is None:
        return {}
    allow = set(allowed or _SUPPORTED_OPTION_KEYS)
    return options.as_provider_payload(tuple(allow))


def infer_placement_from_options(options: LoadOptions | None) -> str:
    """Best-effort placement label from configured offload — not a VRAM claim.

    Returns PhysicalPlacement value strings. HYBRID only when GPU layers are
    explicitly configured as a positive finite offload (not -1 / all).
    """
    if options is None or options.gpu_offload_layers is None:
        return "UNKNOWN"
    ngl = int(options.gpu_offload_layers)
    if ngl == 0:
        return "CPU"
    if ngl < 0:
        # -1 typically means "all layers on GPU" in llama.cpp
        return "GPU"
    return "HYBRID"
