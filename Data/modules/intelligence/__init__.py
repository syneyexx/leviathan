"""LEVIATHAN unified intelligence substrate.

Orchestration and truth surfaces over existing KnowledgeStore / MemoryStore —
never a parallel store.
"""

from .assimilation import AssimilationReceipt, KnowledgeAssimilationService
from .consumer_truth import ConsumerTruthReport, build_consumer_truth
from .embeddings_resolve import (
    resolve_embedding_provider,
    resolve_embedding_provider_auto,
)
from .health import IntelligenceHealthService
from .policy import ReasoningPolicy

__all__ = [
    "AssimilationReceipt",
    "ConsumerTruthReport",
    "IntelligenceHealthService",
    "KnowledgeAssimilationService",
    "ReasoningPolicy",
    "build_consumer_truth",
    "resolve_embedding_provider",
    "resolve_embedding_provider_auto",
]
