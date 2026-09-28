"""Brain — One-Brain access fabric + bounded graph projection.

Graph projection is a view. Access facade compiles typed context from owners.
Brain is not canonical storage and not a second CognitiveRuntime.
"""

from .access import BrainAccessFacade
from .compute import ALGORITHM_VERSION, compute_derived_snapshot, process_brain_compute_job
from .contracts import (
    BrainContext,
    BrainContextRequest,
    BrainEvidenceRef,
    BrainExperienceRef,
    BrainKnowledgeRef,
    BrainMemoryRef,
    BrainSourceRef,
    DomainContext,
    RoleContext,
)
from .facade import BrainEdge, BrainNode, BrainQueryFacade

__all__ = [
    "ALGORITHM_VERSION",
    "BrainAccessFacade",
    "BrainContext",
    "BrainContextRequest",
    "BrainEdge",
    "BrainEvidenceRef",
    "BrainExperienceRef",
    "BrainKnowledgeRef",
    "BrainMemoryRef",
    "BrainNode",
    "BrainQueryFacade",
    "BrainSourceRef",
    "DomainContext",
    "RoleContext",
    "compute_derived_snapshot",
    "process_brain_compute_job",
]
