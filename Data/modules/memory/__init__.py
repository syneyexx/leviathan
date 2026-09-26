"""Controlled Memory — separate from Knowledge; never auto model-output truth."""

from .consolidation import ConsolidationResult, MemoryConsolidator, SemanticCandidate
from .store import MemoryStore
from .types import (
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryTrustState,
    normalize_trust_state,
)

__all__ = [
    "ConsolidationResult",
    "MemoryConsolidator",
    "MemoryKind",
    "MemoryRecord",
    "MemoryScope",
    "MemoryStatus",
    "MemoryStore",
    "MemoryTrustState",
    "SemanticCandidate",
    "normalize_trust_state",
]
