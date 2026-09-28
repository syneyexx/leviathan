"""Bounded environment policy for managed serving children.

Do not pass the complete host environment (and its secrets) to children.
"""

from __future__ import annotations

import os
from typing import Mapping


# Explicit allow-list prefixes / keys for serving children.
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
    "VLLM_",
    "HF_",
    "TRANSFORMERS_",
    "TORCH_",
    "NCCL_",
    "UCX_",
)


def build_serving_child_env(
    extra: Mapping[str, str] | None = None,
    *,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a minimal env for a managed model-server child process."""
    source = dict(base if base is not None else os.environ)
    out: dict[str, str] = {}
    for key, value in source.items():
        if key in _ALLOWED_EXACT:
            out[key] = value
            continue
        if any(key.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
            out[key] = value
    if extra:
        for key, value in extra.items():
            if value is None:
                continue
            out[str(key)] = str(value)
    # Ensure PATH exists so relative binaries remain resolvable when allow-list
    # filtered an empty PATH on unusual hosts.
    if "PATH" not in out and "PATH" in source:
        out["PATH"] = source["PATH"]
    return out
