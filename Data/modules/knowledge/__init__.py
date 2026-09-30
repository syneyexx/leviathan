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
from .staged_retrieval import StagedRetrievalResult, StagedRetriever, resolve_use_reranker
from .store import KnowledgeStore
from .preparation import (
    NORMALIZATION_VERSION,
    PreparedChunk,
    PreparedDocumentIndex,
    build_chunk_plan,
    normalize_document_text,
)
from .execution_gate import (
    workers_externalize_enabled,
    refuse_inline_knowledge,
)
from .library import (
    LIBRARY_TYPE_IDS,
    LIBRARY_TYPE_LABELS,
    infer_library_type,
    normalize_library_type,
)
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
    "LIBRARY_TYPE_IDS",
    "LIBRARY_TYPE_LABELS",
    "LocalHashEmbeddingProvider",
    "NORMALIZATION_VERSION",
    "NullEmbeddingProvider",
    "PreparedChunk",
    "PreparedDocumentIndex",
    "RelationClass",
    "RerankerProvider",
    "RetrievalHit",
    "RetrievalMode",
    "RetrievalQuery",
    "RetrievalTrace",
    "SentenceTransformersEmbeddingProvider",
    "StagedRetrievalResult",
    "StagedRetriever",
    "TextSpan",
    "WhyBucket",
    "WhyLibrary",
    "WhyRecord",
    "bm25_relevance",
    "build_chunk_plan",
    "build_embedding_provider",
    "infer_library_type",
    "normalize_document_text",
    "normalize_library_type",
    "reciprocal_rank_fusion",
    "refuse_inline_knowledge",
    "resolve_use_reranker",
    "workers_externalize_enabled",
]
