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
from .retrieval import (
    CitationCheck,
    HybridRetriever,
    RetrievalHit,
    RetrievalMode,
    RetrievalQuery,
    RetrievalTrace,
    bm25_relevance,
    reciprocal_rank_fusion,
)
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
    "RetrievalMode",
    "RetrievalQuery",
    "RetrievalTrace",
    "SentenceTransformersEmbeddingProvider",
    "TextSpan",
    "WhyBucket",
    "WhyLibrary",
    "WhyRecord",
    "bm25_relevance",
    "build_embedding_provider",
    "reciprocal_rank_fusion",
]
