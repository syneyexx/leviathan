"""Bounded environment policy for trainer subprocesses.

Do not copy the complete host environment (API/provider/broker secrets) into
trainer children. Pass only runtime/CUDA/library paths plus explicit extras.
"""

from __future__ import annotations

import os
from typing import Mapping


_ALLOWED_EXACT = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "USERNAME",
        "USER",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "PYTHONUTF8",
        "PYTHONIOENCODING",
        "PYTHONPATH",
        "PYTHONNOUSERSITE",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
    }
)

_ALLOWED_PREFIXES = (
    "CUDA_",
    "NVIDIA_",
    "HIP_",
    "ROCR_",
    "HSA_",
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
    "GGML_",
    "LLAMA_",
    "HF_",
    "TRANSFORMERS_",
    "TORCH_",
    "NCCL_",
    "UCX_",
    "BITSANDBYTES_",
    "PEFT_",
    "ACCELERATE_",
    "TOKENIZERS_",
    "SAFETENSORS_",
    "OMP_",
    "MKL_",
    "OPENBLAS_",
    "LEVIATHAN_TRAINING_",
)

# Never forward these even if they match a prefix (defense in depth).
_DENIED_SUBSTRINGS = (
    "SECRET",
    "PASSWORD",
    "TOKEN",
    "API_KEY",
    "APIKEY",
    "AUTHORIZATION",
    "ALPACA",
    "BROKER",
    "AWS_",
    "GITHUB",
    "GITLAB",
    "OPENAI",
    "ANTHROPIC",
    "DATABASE",
    "DB_PASS",
    "PRIVATE_KEY",
)


def build_trainer_child_env(
    extra: Mapping[str, str] | None = None,
    *,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a minimal env for an owned trainer subprocess."""
    source = dict(base if base is not None else os.environ)
    out: dict[str, str] = {}
    for key, value in source.items():
        upper = key.upper()
        if any(deny in upper for deny in _DENIED_SUBSTRINGS):
            continue
        if key in _ALLOWED_EXACT:
            out[key] = value
            continue
        if any(key.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
            out[key] = value
    if extra:
        for key, value in extra.items():
            if value is None:
                continue
            upper = str(key).upper()
            if any(deny in upper for deny in _DENIED_SUBSTRINGS):
                continue
            out[str(key)] = str(value)
    if "PATH" not in out and "PATH" in source:
        out["PATH"] = source["PATH"]
    # Prefer offline/local assets for production training unless extras override.
    if extra is None or "HF_HUB_OFFLINE" not in extra:
        out["HF_HUB_OFFLINE"] = "1"
    if extra is None or "TRANSFORMERS_OFFLINE" not in extra:
        out["TRANSFORMERS_OFFLINE"] = "1"
    if extra is None or "HF_DATASETS_OFFLINE" not in extra:
        out["HF_DATASETS_OFFLINE"] = "1"
    return out
