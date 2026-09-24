"""Deterministic cache eligibility policy — never an LLM decision."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CacheType(str, Enum):
    TOKENIZATION = "tokenization"
    CONTEXT_COMPILE = "context_compile"
    RETRIEVAL = "retrieval"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    EXACT_RESULT = "exact_result"
    SEMANTIC = "semantic"
    RUNTIME_PREFIX = "runtime_prefix"


class CacheScope(str, Enum):
    PROCESS = "PROCESS"
    MODEL_WORKER = "MODEL_WORKER"
    USER = "USER"
    PROJECT = "PROJECT"
    WORKSPACE = "WORKSPACE"
    GLOBAL_PUBLIC_CONTENT = "GLOBAL_PUBLIC_CONTENT"


class CacheBypassReason(str, Enum):
    CACHE_DISABLED = "CACHE_DISABLED"
    NOT_CACHEABLE_OPERATION = "NOT_CACHEABLE_OPERATION"
    SIDE_EFFECTS = "SIDE_EFFECTS"
    VOLATILE_EXTERNAL_STATE = "VOLATILE_EXTERNAL_STATE"
    SENSITIVE_CONTENT = "SENSITIVE_CONTENT"
    STREAMING_CLIENT_SEMANTICS = "STREAMING_CLIENT_SEMANTICS"
    STOCHASTIC_POLICY = "STOCHASTIC_POLICY"
    MISSING_DEPENDENCY_FINGERPRINT = "MISSING_DEPENDENCY_FINGERPRINT"
    SEMANTIC_CACHE_DISABLED = "SEMANTIC_CACHE_DISABLED"
    UNSUPPORTED_RUNTIME = "UNSUPPORTED_RUNTIME"
    CROSS_SCOPE = "CROSS_SCOPE"
    CACHE_HIT = "CACHE_HIT"
    CACHE_MISS = "CACHE_MISS"
    ELIGIBLE = "ELIGIBLE"


# Operations explicitly allowed for exact result caching (opt-in).
DEFAULT_EXACT_RESULT_OPERATIONS: frozenset[str] = frozenset(
    {
        "classification.deterministic",
        "schema.normalize",
        "extraction.stable",
        "query.rewrite",
        "evaluation.helper",
    }
)

# Semantic cache candidates (still default OFF globally).
DEFAULT_SEMANTIC_OPERATIONS: frozenset[str] = frozenset(
    {
        "query.normalize",
        "query.rewrite",
        "intent.classify",
        "document.metadata_classify",
        "schema.semantic_normalize",
    }
)

# Never semantic-cache these.
SEMANTIC_FORBIDDEN_OPERATIONS: frozenset[str] = frozenset(
    {
        "chat.final",
        "research.final",
        "coding.patch_plan",
        "agent.action",
        "trading.decision",
        "web.current",
        "memory.personal",
        "approval.decision",
        "medical.current",
        "legal.current",
        "financial.current",
    }
)


@dataclass(frozen=True)
class CacheEligibility:
    cacheable: bool
    cache_type: CacheType | None
    scope: CacheScope
    reason: CacheBypassReason
    ttl_seconds: float | None = None
    sensitivity: str = "normal"
    invalidation_generation: int | None = None
    dependencies: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "cacheable": self.cacheable,
            "cacheType": self.cache_type.value if self.cache_type else None,
            "scope": self.scope.value,
            "reason": self.reason.value,
            "ttlSeconds": self.ttl_seconds,
            "sensitivity": self.sensitivity,
            "invalidationGeneration": self.invalidation_generation,
            "dependencies": list(self.dependencies),
            "details": dict(self.details),
        }


@dataclass
class CachePolicyConfig:
    caches_enabled: bool = True
    tokenization_enabled: bool = True
    context_compile_enabled: bool = True
    retrieval_enabled: bool = True
    embedding_enabled: bool = True
    rerank_enabled: bool = True
    exact_result_enabled: bool = False
    semantic_enabled: bool = False  # default OFF
    semantic_threshold: float = 0.92
    exact_result_operations: frozenset[str] = DEFAULT_EXACT_RESULT_OPERATIONS
    semantic_operations: frozenset[str] = DEFAULT_SEMANTIC_OPERATIONS


class CachePolicyEngine:
    def __init__(self, config: CachePolicyConfig | None = None) -> None:
        self.config = config or CachePolicyConfig()

    def evaluate(
        self,
        *,
        cache_type: CacheType,
        operation_id: str | None = None,
        has_side_effects: bool = False,
        streaming: bool = False,
        stochastic: bool = False,
        sensitive: bool = False,
        volatile_external: bool = False,
        dependency_fingerprint_complete: bool = True,
        scope: CacheScope = CacheScope.PROCESS,
        temperature: float | None = None,
    ) -> CacheEligibility:
        cfg = self.config
        if not cfg.caches_enabled:
            return CacheEligibility(False, None, scope, CacheBypassReason.CACHE_DISABLED)

        type_enabled = {
            CacheType.TOKENIZATION: cfg.tokenization_enabled,
            CacheType.CONTEXT_COMPILE: cfg.context_compile_enabled,
            CacheType.RETRIEVAL: cfg.retrieval_enabled,
            CacheType.EMBEDDING: cfg.embedding_enabled,
            CacheType.RERANK: cfg.rerank_enabled,
            CacheType.EXACT_RESULT: cfg.exact_result_enabled,
            CacheType.SEMANTIC: cfg.semantic_enabled,
            CacheType.RUNTIME_PREFIX: True,
        }.get(cache_type, False)

        if not type_enabled:
            reason = (
                CacheBypassReason.SEMANTIC_CACHE_DISABLED
                if cache_type == CacheType.SEMANTIC
                else CacheBypassReason.CACHE_DISABLED
            )
            return CacheEligibility(False, cache_type, scope, reason)

        if has_side_effects:
            return CacheEligibility(False, cache_type, scope, CacheBypassReason.SIDE_EFFECTS)
        if sensitive and cache_type in {CacheType.EXACT_RESULT, CacheType.SEMANTIC, CacheType.RETRIEVAL}:
            return CacheEligibility(False, cache_type, scope, CacheBypassReason.SENSITIVE_CONTENT)
        if volatile_external:
            return CacheEligibility(False, cache_type, scope, CacheBypassReason.VOLATILE_EXTERNAL_STATE)
        if streaming and cache_type in {CacheType.EXACT_RESULT, CacheType.SEMANTIC}:
            return CacheEligibility(False, cache_type, scope, CacheBypassReason.STREAMING_CLIENT_SEMANTICS)
        if stochastic or (temperature is not None and temperature > 0 and cache_type == CacheType.EXACT_RESULT):
            return CacheEligibility(False, cache_type, scope, CacheBypassReason.STOCHASTIC_POLICY)
        if not dependency_fingerprint_complete:
            return CacheEligibility(
                False, cache_type, scope, CacheBypassReason.MISSING_DEPENDENCY_FINGERPRINT
            )

        if cache_type == CacheType.EXACT_RESULT:
            op = operation_id or ""
            if op not in cfg.exact_result_operations:
                return CacheEligibility(
                    False, cache_type, scope, CacheBypassReason.NOT_CACHEABLE_OPERATION
                )

        if cache_type == CacheType.SEMANTIC:
            op = operation_id or ""
            if op in SEMANTIC_FORBIDDEN_OPERATIONS:
                return CacheEligibility(
                    False, cache_type, scope, CacheBypassReason.NOT_CACHEABLE_OPERATION
                )
            if op not in cfg.semantic_operations:
                return CacheEligibility(
                    False, cache_type, scope, CacheBypassReason.NOT_CACHEABLE_OPERATION
                )

        ttl = None
        if cache_type == CacheType.SEMANTIC:
            ttl = 3600.0
        elif cache_type == CacheType.EXACT_RESULT:
            ttl = 86400.0
        elif cache_type == CacheType.RETRIEVAL:
            ttl = 600.0

        return CacheEligibility(
            True,
            cache_type,
            scope,
            CacheBypassReason.ELIGIBLE,
            ttl_seconds=ttl,
            sensitivity="sensitive" if sensitive else "normal",
        )
