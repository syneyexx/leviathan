"""Brain — One-Brain access fabric + bounded graph projection.

Graph projection is a view. Access facade compiles typed context from owners.
Brain is not canonical storage and not a second CognitiveRuntime.
"""

from .access import BrainAccessFacade
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
]
