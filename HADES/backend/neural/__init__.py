"""HADES Neural Memory — isolated experimental subsystem.

Optional PyTorch-backed associative memory. Normal HADES must not import
trainable modules at startup; use :func:`neural_available` / contracts only.
Default mode is OFF. Not wired into ModelGateway or production inference.
"""

from __future__ import annotations

from neural.contracts import NeuralMode, NeuralMemoryMetrics
from neural.deps import neural_available, require_torch
from neural.errors import (
    NeuralCheckpointCorrupt,
    NeuralCheckpointIncompatible,
    NeuralDependencyUnavailable,
    NeuralDomainMismatch,
    NeuralMemoryUpdateRejected,
    NeuralModeUnsupported,
    NeuralNumericalInstability,
    NeuralPersonalDataRejected,
    NeuralRuntimeCancelled,
    NeuralRuntimeFailed,
    NeuralRuntimeNotReady,
    NeuralRuntimeUnavailable,
    NeuralSecretRejected,
)

__all__ = [
    "NeuralMode",
    "NeuralMemoryMetrics",
    "neural_available",
    "require_torch",
    "NeuralCheckpointCorrupt",
    "NeuralCheckpointIncompatible",
    "NeuralDependencyUnavailable",
    "NeuralDomainMismatch",
    "NeuralMemoryUpdateRejected",
    "NeuralModeUnsupported",
    "NeuralNumericalInstability",
    "NeuralPersonalDataRejected",
    "NeuralRuntimeCancelled",
    "NeuralRuntimeFailed",
    "NeuralRuntimeNotReady",
    "NeuralRuntimeUnavailable",
    "NeuralSecretRejected",
]
