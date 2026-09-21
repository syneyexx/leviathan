"""Optional dependency detection for neural memory.

Importing this module must never import torch. Heavy ML stays out of normal
HADES startup paths.
"""

from __future__ import annotations

import importlib.util
from typing import Any

from neural.errors import NeuralDependencyUnavailable


def neural_available() -> bool:
    return importlib.util.find_spec("torch") is not None


def require_torch() -> Any:
    if not neural_available():
        raise NeuralDependencyUnavailable(
            "PyTorch is not installed; neural memory is unavailable.",
            detail={"required_package": "torch"},
        )
    import torch

    return torch


def torch_info() -> dict[str, Any]:
    if not neural_available():
        return {"available": False, "version": None, "cuda": False}
    torch = require_torch()
    version = getattr(torch, "__version__", None)
    cuda = bool(getattr(torch, "cuda", None) and torch.cuda.is_available())
    return {"available": True, "version": version, "cuda": cuda}
