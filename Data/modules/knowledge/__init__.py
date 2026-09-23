"""Knowledge V2/V3 — documents, chunks, provenance, hybrid retrieval, atlas, deep recall."""

from .atlas import AtlasRecord, AtlasScale, AtlasStore
from .deep_recall import DeepRecallRequest, DeepRecallResult, DeepRecallService
from .economy import CognitiveEconomyGovernor, EconomyDecision
from .embeddings import (
    EmbeddingProvider,
    LocalHashEmbeddingProvider,
    NullEmbeddingProvider,
    RerankerProvider,
    SentenceTransformersEmbeddingProvider,
    build_embedding_provider,
)
from .retrieval import CitationCheck, HybridRetriever, RetrievalHit, RetrievalQuery, RetrievalTrace
from .store import KnowledgeStore
from .types import (
    ChunkRecord,
    DirectionalRelationAtom,
    DocumentRecord,
    IngestStatus,
    RelationClass,
    TextSpan,
)
from .why_library import WhyBucket, WhyLibrary, WhyRecord

__all__ = [
    "AtlasRecord",
    "AtlasScale",
    "AtlasStore",
    "ChunkRecord",
    "CognitiveEconomyGovernor",
    "DeepRecallRequest",
    "DeepRecallResult",
    "DeepRecallService",
    "DirectionalRelationAtom",
    "DocumentRecord",
    "EconomyDecision",
    "EmbeddingProvider",
    "CitationCheck",
    "HybridRetriever",
    "IngestStatus",
    "KnowledgeStore",
    "LocalHashEmbeddingProvider",
    "NullEmbeddingProvider",
    "RelationClass",
    "RerankerProvider",
    "RetrievalHit",
    "RetrievalQuery",
    "RetrievalTrace",
    "SentenceTransformersEmbeddingProvider",
    "TextSpan",
    "WhyBucket",
    "WhyLibrary",
    "WhyRecord",
    "build_embedding_provider",
]
