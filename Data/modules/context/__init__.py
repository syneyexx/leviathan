"""Context Engine — sole model prompt/context compiler (U061) + Inference Efficiency Plane."""

from .bounded_cache import BoundedLRUCache, CacheStats
from .budget import (
    CONTEXT_WINDOW_EXCEEDED,
    ContextBudgetPlan,
    ContextBudgetPlanner,
    ContextFitDecision,
    ContextFitState,
)
from .builder import ContextBuilder
from .cache_policy import (
    CacheBypassReason,
    CacheEligibility,
    CachePolicyConfig,
    CachePolicyEngine,
    CacheScope,
    CacheType,
)
from .compaction import CompactionResult, compact_conversation, extract_hard_constraints
from .efficiency import (
    EfficiencyMetrics,
    InferenceEfficiencyPlane,
    RuntimeCacheAffinity,
    get_efficiency_plane,
    set_efficiency_plane,
)
from .fingerprints import (
    CONTEXT_COMPILER_VERSION,
    ContextFingerprintInputs,
    StablePrefixInputs,
    build_stable_prefix_fingerprint,
)
from .fit import preflight_context_fit, raise_if_unfit
from .hierarchical_compaction import (
    CompactionSegment,
    HierarchicalCompactionResult,
    compact_hierarchical,
)
from .multimodal import (
    MultimodalMessage,
    MultimodalPart,
    MultimodalSession,
    MultimodalSessionRegistry,
    PartKind,
    new_sync_id,
)
from .singleflight import SingleFlight
from .snapshots import ContextSnapshot, snapshot_context_pack
from .tokenization import (
    FixtureTokenizer,
    TokenCountResult,
    TokenCountSource,
    TokenPrecision,
    TokenizationRequest,
    TokenizationService,
    get_tokenization_service,
    set_tokenization_service,
)
from .types import (
    CONTEXT_LAYERS,
    BudgetLedger,
    BudgetLedgerEntry,
    ContextPack,
    ContextSection,
    estimate_tokens,
)

__all__ = [
    "CONTEXT_COMPILER_VERSION",
    "CONTEXT_LAYERS",
    "CONTEXT_WINDOW_EXCEEDED",
    "BoundedLRUCache",
    "BudgetLedger",
    "BudgetLedgerEntry",
    "CacheBypassReason",
    "CacheEligibility",
    "CachePolicyConfig",
    "CachePolicyEngine",
    "CacheScope",
    "CacheStats",
    "CacheType",
    "CompactionResult",
    "CompactionSegment",
    "ContextBudgetPlan",
    "ContextBudgetPlanner",
    "ContextBuilder",
    "ContextFingerprintInputs",
    "ContextFitDecision",
    "ContextFitState",
    "ContextPack",
    "ContextSection",
    "ContextSnapshot",
    "EfficiencyMetrics",
    "FixtureTokenizer",
    "HierarchicalCompactionResult",
    "InferenceEfficiencyPlane",
    "MultimodalMessage",
    "MultimodalPart",
    "MultimodalSession",
    "MultimodalSessionRegistry",
    "PartKind",
    "RuntimeCacheAffinity",
    "SingleFlight",
    "StablePrefixInputs",
    "TokenCountResult",
    "TokenCountSource",
    "TokenPrecision",
    "TokenizationRequest",
    "TokenizationService",
    "build_stable_prefix_fingerprint",
    "compact_conversation",
    "compact_hierarchical",
    "estimate_tokens",
    "extract_hard_constraints",
    "get_efficiency_plane",
    "get_tokenization_service",
    "new_sync_id",
    "preflight_context_fit",
    "raise_if_unfit",
    "set_efficiency_plane",
    "set_tokenization_service",
    "snapshot_context_pack",
]
