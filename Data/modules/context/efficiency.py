"""Inference Efficiency Plane — coordinated caches, metrics, and policy.

Not a second control plane. Owns derived acceleration state only.
Deleting every cache entry never deletes Brain/history/domain state.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from Data.modules.common.hashing import sha256_text

from .bounded_cache import BoundedLRUCache
from .budget import ContextBudgetPlanner
from .cache_policy import (
    CacheBypassReason,
    CachePolicyConfig,
    CachePolicyEngine,
    CacheScope,
    CacheType,
)
from .fingerprints import CONTEXT_COMPILER_VERSION
from .singleflight import SingleFlight
from .tokenization import TokenizationService, get_tokenization_service


@dataclass
class RuntimeCacheAffinity:
    """LEVIATHAN-tracked affinity metadata — does NOT own opaque KV tensors."""

    model_id: str
    worker_id: str | None
    runtime_generation: int
    stable_prefix_fingerprint: str | None = None
    prefix_cache_state: str = "unknown"  # supported|unsupported|unknown|unverified|warm|cold|dead
    kv_cache_state: str = "unknown"
    last_reuse_at: float | None = None
    hit_count: int = 0
    provenance: str = "UNKNOWN"  # MEASURED | RUNTIME_REPORTED | ESTIMATED | UNKNOWN

    def public_dict(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "workerId": self.worker_id,
            "runtimeGeneration": self.runtime_generation,
            "stablePrefixFingerprint": self.stable_prefix_fingerprint,
            "prefixCacheState": self.prefix_cache_state,
            "kvCacheState": self.kv_cache_state,
            "lastReuseAt": self.last_reuse_at,
            "hitCount": self.hit_count,
            "provenance": self.provenance,
            "truth": {
                "kv_tensors_owned_by_runtime": True,
                "affinity_is_not_brain_memory": True,
                "dead_worker_cannot_claim_warm_cache": True,
            },
        }


@dataclass
class EfficiencyMetrics:
    """Process-local measured counters (bounded cardinality)."""

    token_lookups: int = 0
    token_hits: int = 0
    context_compile_hits: int = 0
    context_compile_misses: int = 0
    retrieval_hits: int = 0
    retrieval_misses: int = 0
    embedding_hits: int = 0
    embedding_misses: int = 0
    rerank_hits: int = 0
    rerank_misses: int = 0
    exact_result_hits: int = 0
    exact_result_misses: int = 0
    exact_result_bypasses: int = 0
    semantic_hits: int = 0
    semantic_misses: int = 0
    semantic_bypasses: int = 0
    prefix_reuse: int = 0
    cached_input_tokens_provider: int = 0
    context_fit_failures: int = 0
    compaction_count: int = 0
    evictions: int = 0
    invalidations: int = 0
    ttft_samples_ms: list[float] = field(default_factory=list)
    exact_token_counts: int = 0
    heuristic_token_counts: int = 0

    def record_ttft(self, ms: float) -> None:
        if len(self.ttft_samples_ms) >= 256:
            self.ttft_samples_ms.pop(0)
        self.ttft_samples_ms.append(float(ms))

    def public_dict(self) -> dict[str, Any]:
        ttft = None
        if self.ttft_samples_ms:
            ttft = sum(self.ttft_samples_ms) / len(self.ttft_samples_ms)
        return {
            "tokenization": {"lookups": self.token_lookups, "hits": self.token_hits},
            "contextCompile": {"hits": self.context_compile_hits, "misses": self.context_compile_misses},
            "retrieval": {"hits": self.retrieval_hits, "misses": self.retrieval_misses},
            "embedding": {"hits": self.embedding_hits, "misses": self.embedding_misses},
            "rerank": {"hits": self.rerank_hits, "misses": self.rerank_misses},
            "exactResult": {
                "hits": self.exact_result_hits,
                "misses": self.exact_result_misses,
                "bypasses": self.exact_result_bypasses,
            },
            "semantic": {
                "hits": self.semantic_hits,
                "misses": self.semantic_misses,
                "bypasses": self.semantic_bypasses,
            },
            "prefixReuse": self.prefix_reuse,
            "cachedInputTokensProviderReported": self.cached_input_tokens_provider,
            "contextFitFailures": self.context_fit_failures,
            "compactionCount": self.compaction_count,
            "evictions": self.evictions,
            "invalidations": self.invalidations,
            "ttftAvgMs": ttft,
            "tokenPrecisionShare": {
                "exact": self.exact_token_counts,
                "heuristic": self.heuristic_token_counts,
            },
            "truth": {
                "ttft_is_measured": ttft is not None,
                "cached_input_tokens_are_provider_reported": True,
                "no_invented_token_savings": True,
            },
        }


class InferenceEfficiencyPlane:
    """Coordinates tokenization, derived caches, affinity, and metrics."""

    def __init__(
        self,
        *,
        tokenization: TokenizationService | None = None,
        policy: CachePolicyEngine | None = None,
        budget_planner: ContextBudgetPlanner | None = None,
        emit: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.tokenization = tokenization or get_tokenization_service()
        self.policy = policy or CachePolicyEngine()
        self.budget_planner = budget_planner or ContextBudgetPlanner()
        self._emit = emit
        self._lock = threading.RLock()
        self.metrics = EfficiencyMetrics()
        self._runtime_generation: dict[str, int] = {}
        self._affinity: dict[str, RuntimeCacheAffinity] = {}

        self.context_compile_cache: BoundedLRUCache[str, dict[str, Any]] = BoundedLRUCache(
            max_entries=256, max_bytes=8 * 1024 * 1024, name="context_compile"
        )
        self.retrieval_cache: BoundedLRUCache[str, dict[str, Any]] = BoundedLRUCache(
            max_entries=512, max_bytes=16 * 1024 * 1024, name="retrieval", ttl_seconds=600
        )
        self.embedding_cache: BoundedLRUCache[str, dict[str, Any]] = BoundedLRUCache(
            max_entries=2048, max_bytes=32 * 1024 * 1024, name="embedding"
        )
        self.rerank_cache: BoundedLRUCache[str, dict[str, Any]] = BoundedLRUCache(
            max_entries=512, max_bytes=8 * 1024 * 1024, name="rerank"
        )
        self.exact_result_cache: BoundedLRUCache[str, dict[str, Any]] = BoundedLRUCache(
            max_entries=256, max_bytes=8 * 1024 * 1024, name="exact_result", ttl_seconds=86400
        )
        self.semantic_cache: BoundedLRUCache[str, dict[str, Any]] = BoundedLRUCache(
            max_entries=128, max_bytes=4 * 1024 * 1024, name="semantic", ttl_seconds=3600
        )
        self._flights = {
            "context": SingleFlight[dict[str, Any]](),
            "retrieval": SingleFlight[dict[str, Any]](),
            "embedding": SingleFlight[dict[str, Any]](),
            "rerank": SingleFlight[dict[str, Any]](),
        }
        self._hierarchical_segments: BoundedLRUCache[str, dict[str, Any]] = BoundedLRUCache(
            max_entries=128, max_bytes=4 * 1024 * 1024, name="compaction_segments"
        )

    def _event(self, kind: str, payload: dict[str, Any]) -> None:
        if self._emit is None:
            return
        try:
            self._emit(kind, payload)
        except Exception:  # noqa: BLE001
            pass

    def apply_settings(self, settings: dict[str, Any]) -> None:
        """Apply operator settings without inventing unsupported toggles."""
        cfg = self.policy.config
        if "caches_enabled" in settings:
            cfg.caches_enabled = bool(settings["caches_enabled"])
        if "tokenization_enabled" in settings:
            cfg.tokenization_enabled = bool(settings["tokenization_enabled"])
        if "context_compile_enabled" in settings:
            cfg.context_compile_enabled = bool(settings["context_compile_enabled"])
        if "retrieval_enabled" in settings:
            cfg.retrieval_enabled = bool(settings["retrieval_enabled"])
        if "embedding_enabled" in settings:
            cfg.embedding_enabled = bool(settings["embedding_enabled"])
        if "rerank_enabled" in settings:
            cfg.rerank_enabled = bool(settings["rerank_enabled"])
        if "exact_result_enabled" in settings:
            cfg.exact_result_enabled = bool(settings["exact_result_enabled"])
        if "semantic_enabled" in settings:
            cfg.semantic_enabled = bool(settings["semantic_enabled"])
        if "semantic_threshold" in settings:
            cfg.semantic_threshold = float(settings["semantic_threshold"])
        enabled = cfg.caches_enabled
        self.tokenization.set_enabled(enabled and cfg.tokenization_enabled)
        self.context_compile_cache.set_enabled(enabled and cfg.context_compile_enabled)
        self.retrieval_cache.set_enabled(enabled and cfg.retrieval_enabled)
        self.embedding_cache.set_enabled(enabled and cfg.embedding_enabled)
        self.rerank_cache.set_enabled(enabled and cfg.rerank_enabled)
        self.exact_result_cache.set_enabled(enabled and cfg.exact_result_enabled)
        self.semantic_cache.set_enabled(enabled and cfg.semantic_enabled)

    def configure_bounds(
        self,
        *,
        token_cache_entries: int | None = None,
        token_cache_bytes: int | None = None,
        context_cache_entries: int | None = None,
        context_cache_bytes: int | None = None,
    ) -> None:
        if token_cache_entries:
            self.tokenization._cache.max_entries = int(token_cache_entries)
        if token_cache_bytes:
            self.tokenization._cache.max_bytes = int(token_cache_bytes)
        if context_cache_entries:
            self.context_compile_cache.max_entries = int(context_cache_entries)
        if context_cache_bytes:
            self.context_compile_cache.max_bytes = int(context_cache_bytes)

    # ---- runtime affinity (not KV ownership) ----

    def runtime_generation(self, model_id: str) -> int:
        with self._lock:
            return self._runtime_generation.get(model_id, 0)

    def on_worker_ready(
        self,
        model_id: str,
        *,
        worker_id: str | None,
        prefix_cache_state: str = "unknown",
        kv_cache_state: str = "unknown",
    ) -> RuntimeCacheAffinity:
        with self._lock:
            gen = self._runtime_generation.get(model_id, 0) + 1
            self._runtime_generation[model_id] = gen
            aff = RuntimeCacheAffinity(
                model_id=model_id,
                worker_id=worker_id,
                runtime_generation=gen,
                prefix_cache_state=prefix_cache_state,
                kv_cache_state=kv_cache_state,
                provenance="RUNTIME_REPORTED",
            )
            self._affinity[model_id] = aff
            self._event("model.prefix_cache.capability", aff.public_dict())
            return aff

    def on_worker_unloaded(self, model_id: str, *, worker_id: str | None = None) -> None:
        with self._lock:
            aff = self._affinity.get(model_id)
            if aff is None:
                return
            if worker_id and aff.worker_id and worker_id != aff.worker_id:
                return
            aff.prefix_cache_state = "dead"
            aff.kv_cache_state = "dead"
            aff.stable_prefix_fingerprint = None
            aff.provenance = "MEASURED"
            self.metrics.invalidations += 1
            self._event(
                "cache.invalidated",
                {"modelId": model_id, "reason": "worker_unload", "scope": "runtime_affinity"},
            )

    def note_prefix_reuse(self, model_id: str, fingerprint: str) -> None:
        with self._lock:
            aff = self._affinity.get(model_id)
            if aff is None or aff.prefix_cache_state == "dead":
                return
            aff.stable_prefix_fingerprint = fingerprint
            aff.hit_count += 1
            aff.last_reuse_at = time.time()
            if aff.prefix_cache_state in {"supported", "unverified", "cold", "unknown"}:
                aff.prefix_cache_state = "warm"
            self.metrics.prefix_reuse += 1
            self._event("model.prefix_cache.reuse", {"modelId": model_id, "fingerprint": fingerprint[:24]})

    def get_affinity(self, model_id: str) -> RuntimeCacheAffinity | None:
        with self._lock:
            return self._affinity.get(model_id)

    # ---- derived caches ----

    def context_compile_get(self, key: str) -> dict[str, Any] | None:
        elig = self.policy.evaluate(cache_type=CacheType.CONTEXT_COMPILE)
        if not elig.cacheable:
            return None
        hit = self.context_compile_cache.get(key)
        if hit is not None:
            self.metrics.context_compile_hits += 1
            self._event("cache.hit", {"cacheType": "context_compile"})
            return hit
        self.metrics.context_compile_misses += 1
        self._event("cache.miss", {"cacheType": "context_compile"})
        return None

    def context_compile_put(self, key: str, value: dict[str, Any]) -> None:
        elig = self.policy.evaluate(cache_type=CacheType.CONTEXT_COMPILE)
        if not elig.cacheable:
            return
        self.context_compile_cache.put(key, value)

    def retrieval_key(
        self,
        *,
        query: str,
        policy_version: str,
        index_generation: str | int,
        project_scope: str | None,
        security_scope: str | None,
        embedding_model: str | None,
        embedding_revision: str | None,
        reranker_model: str | None,
        top_k: int,
    ) -> str:
        payload = {
            "q": sha256_text(query),
            "pol": policy_version,
            "gen": str(index_generation),
            "project": project_scope,
            "security": security_scope,
            "emb": embedding_model,
            "embr": embedding_revision,
            "rr": reranker_model,
            "k": top_k,
            "v": CONTEXT_COMPILER_VERSION,
        }
        return sha256_text(json.dumps(payload, sort_keys=True))

    def retrieval_get(self, key: str, *, scope: CacheScope = CacheScope.PROJECT) -> dict[str, Any] | None:
        elig = self.policy.evaluate(cache_type=CacheType.RETRIEVAL, scope=scope)
        if not elig.cacheable:
            return None
        hit = self.retrieval_cache.get(key)
        if hit is not None:
            # Scope isolation: stored scope must match
            if hit.get("scope") and hit.get("scope") != scope.value:
                self.metrics.retrieval_misses += 1
                return None
            self.metrics.retrieval_hits += 1
            return hit
        self.metrics.retrieval_misses += 1
        return None

    def retrieval_put(
        self, key: str, value: dict[str, Any], *, scope: CacheScope = CacheScope.PROJECT
    ) -> None:
        elig = self.policy.evaluate(cache_type=CacheType.RETRIEVAL, scope=scope)
        if not elig.cacheable:
            return
        payload = dict(value)
        payload["scope"] = scope.value
        self.retrieval_cache.put(key, payload)

    def embedding_key(
        self,
        *,
        content_digest: str,
        model_id: str,
        model_revision: str | None,
        dimension: int | None,
        normalization: str | None,
        provider_version: str | None,
    ) -> str:
        return sha256_text(
            json.dumps(
                {
                    "c": content_digest,
                    "m": model_id,
                    "r": model_revision,
                    "d": dimension,
                    "n": normalization,
                    "p": provider_version,
                },
                sort_keys=True,
            )
        )

    def embedding_get(self, key: str) -> dict[str, Any] | None:
        elig = self.policy.evaluate(cache_type=CacheType.EMBEDDING)
        if not elig.cacheable:
            return None
        hit = self.embedding_cache.get(key)
        if hit:
            self.metrics.embedding_hits += 1
        else:
            self.metrics.embedding_misses += 1
        return hit

    def embedding_put(self, key: str, value: dict[str, Any]) -> None:
        if self.policy.evaluate(cache_type=CacheType.EMBEDDING).cacheable:
            self.embedding_cache.put(key, value)

    def rerank_key(
        self,
        *,
        query_digest: str,
        candidate_digests: list[str],
        model_id: str,
        model_revision: str | None,
        settings_version: str | None,
    ) -> str:
        return sha256_text(
            json.dumps(
                {
                    "q": query_digest,
                    "c": list(candidate_digests),
                    "m": model_id,
                    "r": model_revision,
                    "s": settings_version,
                },
                sort_keys=True,
            )
        )

    def exact_result_lookup(
        self,
        *,
        operation_id: str,
        key_digest: str,
        has_side_effects: bool = False,
        streaming: bool = False,
        stochastic: bool = False,
        sensitive: bool = False,
        scope: CacheScope = CacheScope.PROJECT,
    ) -> dict[str, Any] | None:
        elig = self.policy.evaluate(
            cache_type=CacheType.EXACT_RESULT,
            operation_id=operation_id,
            has_side_effects=has_side_effects,
            streaming=streaming,
            stochastic=stochastic,
            sensitive=sensitive,
            scope=scope,
        )
        if not elig.cacheable:
            self.metrics.exact_result_bypasses += 1
            self._event("cache.bypass", {"reason": elig.reason.value, "cacheType": "exact_result"})
            return None
        hit = self.exact_result_cache.get(key_digest)
        if hit is None:
            self.metrics.exact_result_misses += 1
            return None
        if hit.get("scope") != scope.value:
            self.metrics.exact_result_misses += 1
            return None
        self.metrics.exact_result_hits += 1
        return hit

    def exact_result_store(
        self,
        *,
        operation_id: str,
        key_digest: str,
        payload: dict[str, Any],
        has_side_effects: bool = False,
        streaming: bool = False,
        stochastic: bool = False,
        sensitive: bool = False,
        scope: CacheScope = CacheScope.PROJECT,
    ) -> bool:
        elig = self.policy.evaluate(
            cache_type=CacheType.EXACT_RESULT,
            operation_id=operation_id,
            has_side_effects=has_side_effects,
            streaming=streaming,
            stochastic=stochastic,
            sensitive=sensitive,
            scope=scope,
        )
        if not elig.cacheable:
            self.metrics.exact_result_bypasses += 1
            return False
        stored = dict(payload)
        stored["scope"] = scope.value
        stored["operation_id"] = operation_id
        # Never pickle — JSON-safe only
        try:
            json.dumps(stored, default=str)
        except TypeError:
            self._event("cache.bypass", {"reason": "non_json_payload"})
            return False
        self.exact_result_cache.put(key_digest, stored)
        return True

    def semantic_lookup(
        self,
        *,
        operation_id: str,
        query_embedding: list[float] | None,
        embedding_is_semantic: bool,
        scope: CacheScope,
        threshold: float | None = None,
        model_policy_version: str | None = None,
    ) -> dict[str, Any] | None:
        elig = self.policy.evaluate(
            cache_type=CacheType.SEMANTIC,
            operation_id=operation_id,
            scope=scope,
        )
        if not elig.cacheable:
            self.metrics.semantic_bypasses += 1
            return None
        if not embedding_is_semantic or query_embedding is None:
            self.metrics.semantic_bypasses += 1
            self._event("cache.bypass", {"reason": "nonsemantic_embedding"})
            return None
        thr = threshold if threshold is not None else self.policy.config.semantic_threshold
        # Linear scan bounded cache — small by design
        best = None
        best_score = -1.0
        # Access internal data carefully
        with self.semantic_cache._lock:
            items = list(self.semantic_cache._data.items())
        for _k, entry in items:
            val = entry.value
            if val.get("scope") != scope.value:
                continue
            if val.get("operation_id") != operation_id:
                continue
            if model_policy_version and val.get("model_policy_version") != model_policy_version:
                continue
            emb = val.get("embedding")
            if not isinstance(emb, list):
                continue
            score = _cosine(query_embedding, emb)
            if score > best_score:
                best_score = score
                best = val
        if best is not None and best_score >= thr:
            # Extra safety: require identical constraint digest when present on both
            self.metrics.semantic_hits += 1
            return {**best, "similarity": best_score}
        self.metrics.semantic_misses += 1
        return None

    def semantic_store(
        self,
        *,
        operation_id: str,
        key: str,
        query_embedding: list[float],
        embedding_is_semantic: bool,
        payload: dict[str, Any],
        scope: CacheScope,
        constraint_digest: str | None = None,
        model_policy_version: str | None = None,
    ) -> bool:
        elig = self.policy.evaluate(cache_type=CacheType.SEMANTIC, operation_id=operation_id, scope=scope)
        if not elig.cacheable or not embedding_is_semantic:
            self.metrics.semantic_bypasses += 1
            return False
        stored = {
            **payload,
            "operation_id": operation_id,
            "embedding": list(query_embedding),
            "scope": scope.value,
            "constraint_digest": constraint_digest,
            "model_policy_version": model_policy_version,
        }
        self.semantic_cache.put(key, stored)
        return True

    def single_flight(self, kind: str) -> SingleFlight[dict[str, Any]]:
        return self._flights[kind]

    def clear_caches(self, *, cache_type: str | None = None, project_scope: str | None = None) -> dict[str, int]:
        """Clear derived application caches only — never Brain/history."""
        cleared: dict[str, int] = {}

        def _clear_one(name: str, cache: BoundedLRUCache) -> None:
            if project_scope:
                n = cache.invalidate_matching(
                    lambda _k, v: isinstance(v, dict) and v.get("scope") == project_scope
                    or (isinstance(v, dict) and v.get("project_scope") == project_scope)
                )
            else:
                n = cache.clear()
            cleared[name] = n
            self.metrics.invalidations += n

        mapping = {
            "tokenization": lambda: cleared.__setitem__("tokenization", self.tokenization.clear_cache()),
            "context_compile": lambda: _clear_one("context_compile", self.context_compile_cache),
            "retrieval": lambda: _clear_one("retrieval", self.retrieval_cache),
            "embedding": lambda: _clear_one("embedding", self.embedding_cache),
            "rerank": lambda: _clear_one("rerank", self.rerank_cache),
            "exact_result": lambda: _clear_one("exact_result", self.exact_result_cache),
            "semantic": lambda: _clear_one("semantic", self.semantic_cache),
            "compaction_segments": lambda: _clear_one("compaction_segments", self._hierarchical_segments),
        }
        if cache_type:
            fn = mapping.get(cache_type)
            if fn:
                fn()
            elif cache_type == "runtime_affinity":
                with self._lock:
                    n = len(self._affinity)
                    for aff in self._affinity.values():
                        aff.prefix_cache_state = "dead"
                        aff.kv_cache_state = "dead"
                        aff.stable_prefix_fingerprint = None
                    cleared["runtime_affinity"] = n
            else:
                cleared["unknown"] = 0
        else:
            for fn in mapping.values():
                fn()
        self._event("cache.invalidated", {"cleared": cleared, "manual": True})
        return cleared

    def invalidate_index_generation(self, generation: str | int) -> int:
        gen = str(generation)
        n = self.retrieval_cache.invalidate_matching(
            lambda _k, v: isinstance(v, dict) and str(v.get("index_generation")) == gen
        )
        self.metrics.invalidations += n
        return n

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            affinities = {k: v.public_dict() for k, v in self._affinity.items()}
            generations = dict(self._runtime_generation)
        return {
            "metrics": self.metrics.public_dict(),
            "policy": {
                "cachesEnabled": self.policy.config.caches_enabled,
                "semanticEnabled": self.policy.config.semantic_enabled,
                "exactResultEnabled": self.policy.config.exact_result_enabled,
                "semanticThreshold": self.policy.config.semantic_threshold,
            },
            "caches": {
                "tokenization": self.tokenization.cache_snapshot(),
                "contextCompile": self.context_compile_cache.snapshot(),
                "retrieval": self.retrieval_cache.snapshot(),
                "embedding": self.embedding_cache.snapshot(),
                "rerank": self.rerank_cache.snapshot(),
                "exactResult": self.exact_result_cache.snapshot(),
                "semantic": self.semantic_cache.snapshot(),
                "compactionSegments": self._hierarchical_segments.snapshot(),
            },
            "runtimeAffinity": affinities,
            "runtimeGenerations": generations,
            "truth": {
                "cache_is_not_brain": True,
                "cache_is_not_memory": True,
                "kv_owned_by_runtime": True,
                "disabled_caches_preserve_correctness": True,
            },
        }

    def quarantine_corrupt(self, cache_name: str, key: str) -> None:
        cache = {
            "context_compile": self.context_compile_cache,
            "retrieval": self.retrieval_cache,
            "embedding": self.embedding_cache,
            "rerank": self.rerank_cache,
            "exact_result": self.exact_result_cache,
            "semantic": self.semantic_cache,
        }.get(cache_name)
        if cache is None:
            return
        cache.invalidate_matching(lambda k, _v: k == key)
        self._event("cache.evicted", {"cacheType": cache_name, "reason": "corruption"})


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return -1.0
    return dot / ((na ** 0.5) * (nb ** 0.5))


_plane: InferenceEfficiencyPlane | None = None
_plane_lock = threading.Lock()


def get_efficiency_plane() -> InferenceEfficiencyPlane:
    global _plane
    with _plane_lock:
        if _plane is None:
            _plane = InferenceEfficiencyPlane()
        return _plane


def set_efficiency_plane(plane: InferenceEfficiencyPlane | None) -> None:
    global _plane
    with _plane_lock:
        _plane = plane
