"""Neuro — advisory signals only. neural signal != authority."""

from .adapters import (
    DeterministicResidualRuntime,
    HFTransformersResidualAdapter,
    LlamaCppResidualAdapter,
    TrtResidualAdapter,
    VllmResidualAdapter,
    build_residual_runtime,
)
from .advisor import NeuroAdvisor
from .cortex import CortexEngagement, CortexPlanner
from .cortex_runtime import NAMED_CORTEX_BLOCKS, CortexBlockSpec, CortexRunReport, CortexRuntime
from .critic import CriticScore, ProcessCritic
from .memory_tiers import NeuroMemoryBundle, NeuroMemoryFacade, NeuroMemoryHit, WorkingMemoryBuffer
from .receipts import ResidualReceiptStore
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
from .residual_orchestrator import (
    ResidualInjectPlan,
    ResidualOrchestrationReport,
    ResidualOrchestrator,
)
from .soak import NeuroSoakHarness, SoakReport, SoakStepResult
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
    "LlamaCppResidualAdapter",
    "MemorySnapshot",
    "NAMED_CORTEX_BLOCKS",
    "NeuroAbsorbService",
    "NeuroAdvisor",
    "NeuroAssessment",
    "NeuroMemoryBundle",
    "NeuroMemoryFacade",
    "NeuroMemoryHit",
    "NeuroSignal",
    "NeuroSnapshotStore",
    "NeuroSoakHarness",
    "ProcessCritic",
    "ResidualForwardRequest",
    "ResidualForwardResult",
    "ResidualHookPoint",
    "ResidualInjectPlan",
    "ResidualInjectReceipt",
    "ResidualInjectRequest",
    "ResidualOrchestrationReport",
    "ResidualOrchestrator",
    "ResidualReadRequest",
    "ResidualReceiptStore",
    "ResidualStreamPort",
    "ResidualTensorRef",
    "SoakReport",
    "SoakStepResult",
    "TrtResidualAdapter",
    "UnsupportedResidualRuntime",
    "VllmResidualAdapter",
    "WorkingMemoryBuffer",
    "build_residual_runtime",
]
