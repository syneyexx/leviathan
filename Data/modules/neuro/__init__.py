"""Neuro — advisory signals only. neural signal != authority."""

from .adapters import (
    DeterministicResidualRuntime,
    HFTransformersResidualAdapter,
    build_residual_runtime,
)
from .advisor import NeuroAdvisor
from .cortex import CortexEngagement, CortexPlanner
from .cortex_runtime import CortexBlockSpec, CortexRunReport, CortexRuntime
from .critic import CriticScore, ProcessCritic
from .memory_tiers import NeuroMemoryBundle, NeuroMemoryFacade, NeuroMemoryHit, WorkingMemoryBuffer
from .residual import (
    ResidualForwardRequest,
    ResidualForwardResult,
    ResidualHookPoint,
    ResidualInjectReceipt,
    ResidualInjectRequest,
    ResidualReadRequest,
    ResidualStreamPort,
    ResidualTensorRef,
    UnsupportedResidualRuntime,
)
from .snapshots import (
    ContrastiveRetrievalHead,
    ContrastiveRetrievalReport,
    MemorySnapshot,
    NeuroAbsorbService,
    NeuroSnapshotStore,
)
from .types import NeuroAssessment, NeuroSignal

__all__ = [
    "ContrastiveRetrievalHead",
    "ContrastiveRetrievalReport",
    "CortexBlockSpec",
    "CortexEngagement",
    "CortexPlanner",
    "CortexRunReport",
    "CortexRuntime",
    "CriticScore",
    "DeterministicResidualRuntime",
    "HFTransformersResidualAdapter",
    "MemorySnapshot",
    "NeuroAbsorbService",
    "NeuroAdvisor",
    "NeuroAssessment",
    "NeuroMemoryBundle",
    "NeuroMemoryFacade",
    "NeuroMemoryHit",
    "NeuroSignal",
    "NeuroSnapshotStore",
    "ProcessCritic",
    "ResidualForwardRequest",
    "ResidualForwardResult",
    "ResidualHookPoint",
    "ResidualInjectReceipt",
    "ResidualInjectRequest",
    "ResidualReadRequest",
    "ResidualStreamPort",
    "ResidualTensorRef",
    "UnsupportedResidualRuntime",
    "WorkingMemoryBuffer",
    "build_residual_runtime",
]
