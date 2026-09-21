"""Typed failures for the neural subsystem.

Fits existing HADES style: stable ``code`` strings + structured detail.
Does not expand the global API ErrorCode enum until product endpoints exist.
"""

from __future__ import annotations

from typing import Any


class NeuralError(RuntimeError):
    code: str = "neural_error"

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = dict(detail or {})

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "detail": dict(self.detail)}


class NeuralDependencyUnavailable(NeuralError):
    code = "neural_dependency_unavailable"


class NeuralCheckpointCorrupt(NeuralError):
    code = "neural_checkpoint_corrupt"


class NeuralCheckpointIncompatible(NeuralError):
    code = "neural_checkpoint_incompatible"


class NeuralMemoryUpdateRejected(NeuralError):
    code = "neural_memory_update_rejected"


class NeuralNumericalInstability(NeuralError):
    code = "neural_numerical_instability"


class NeuralRuntimeUnavailable(NeuralError):
    code = "neural_runtime_unavailable"


class NeuralRuntimeOOM(NeuralError):
    code = "neural_runtime_oom"


class NeuralModeUnsupported(NeuralError):
    code = "neural_mode_unsupported"


class NeuralRuntimeNotReady(NeuralError):
    code = "neural_runtime_not_ready"


class NeuralRuntimeCancelled(NeuralError):
    code = "neural_runtime_cancelled"


class NeuralRuntimeFailed(NeuralError):
    code = "neural_runtime_failed"


class NeuralCandidateRejected(NeuralError):
    code = "neural_candidate_rejected"


class NeuralPromotionFailed(NeuralError):
    code = "neural_promotion_failed"


class NeuralRollbackFailed(NeuralError):
    code = "neural_rollback_failed"


class NeuralUpdateUnstable(NeuralError):
    code = "neural_update_unstable"


class NeuralSecretRejected(NeuralError):
    code = "neural_secret_rejected"


class NeuralPersonalDataRejected(NeuralError):
    code = "neural_personal_data_rejected"


class NeuralDomainMismatch(NeuralError):
    code = "neural_domain_mismatch"


class NeuralCapacityExceeded(NeuralError):
    code = "neural_capacity_exceeded"
